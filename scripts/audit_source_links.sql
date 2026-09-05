\set ON_ERROR_STOP on

BEGIN TRANSACTION READ ONLY;

-- Multiple SMS payloads assigned to one transaction.
-- Any returned row requires review; the query never modifies data.
WITH sms AS (
    SELECT
        l.transaction_id,
        o.id AS observation_id,
        o.source_payload_id,
        o.amount,
        o.currency,
        lower(
            trim(
                regexp_replace(
                    COALESCE(o.description, ''),
                    '[^a-zA-Z0-9]+',
                    ' ',
                    'g'
                )
            )
        ) AS merchant_key,
        (
            COALESCE(
                o.transaction_datetime,
                o.posting_datetime,
                p.received_at,
                p.created_at
            ) AT TIME ZONE COALESCE(
                NULLIF(p.ingestion_metadata ->> 'source_timezone', ''),
                c.timezone,
                a.timezone,
                'UTC'
            )
        )::date AS source_date,
        l.match_method
    FROM transaction_source_links AS l
    JOIN transaction_observations AS o
        ON o.id = l.observation_id
    JOIN source_payloads AS p
        ON p.id = o.source_payload_id
    LEFT JOIN cards AS c
        ON c.id = o.card_id
    LEFT JOIN accounts AS a
        ON a.id = c.account_id
    WHERE p.source_kind = 'sms'
      AND p.media_type = 'text/plain'
)
SELECT
    a.transaction_id,
    a.observation_id AS observation_id_1,
    a.source_payload_id AS source_payload_id_1,
    a.source_date AS source_date_1,
    a.match_method AS match_method_1,
    b.observation_id AS observation_id_2,
    b.source_payload_id AS source_payload_id_2,
    b.source_date AS source_date_2,
    b.match_method AS match_method_2,
    a.amount AS amount_1,
    a.currency AS currency_1,
    a.merchant_key AS merchant_key_1,
    b.amount AS amount_2,
    b.currency AS currency_2,
    b.merchant_key AS merchant_key_2
FROM sms AS a
JOIN sms AS b
    ON b.transaction_id = a.transaction_id
   AND b.observation_id > a.observation_id
   AND b.source_payload_id != a.source_payload_id
ORDER BY a.transaction_id, a.source_date, a.observation_id;

-- Pairwise date consistency using the statement timezone when either side is a
-- statement; otherwise each observation's source/card/account timezone.
WITH dated_observations AS (
    SELECT
        l.transaction_id,
        o.id AS observation_id,
        p.source_kind,
        COALESCE(o.transaction_datetime, o.posting_datetime) AS observed_at,
        COALESCE(
            NULLIF(p.ingestion_metadata ->> 'source_timezone', ''),
            c.timezone,
            a.timezone,
            'UTC'
        ) AS source_timezone
    FROM transaction_source_links AS l
    JOIN transaction_observations AS o
        ON o.id = l.observation_id
    JOIN source_payloads AS p
        ON p.id = o.source_payload_id
    LEFT JOIN cards AS c
        ON c.id = o.card_id
    LEFT JOIN accounts AS a
        ON a.id = c.account_id
    WHERE o.transaction_datetime IS NOT NULL
       OR o.posting_datetime IS NOT NULL
), inconsistent_pairs AS (
    SELECT
        left_observation.transaction_id,
        left_observation.observation_id AS observation_id_1,
        right_observation.observation_id AS observation_id_2,
        comparison.source_timezone,
        (
            left_observation.observed_at
            AT TIME ZONE comparison.source_timezone
        )::date AS observation_date_1,
        (
            right_observation.observed_at
            AT TIME ZONE comparison.source_timezone
        )::date AS observation_date_2
    FROM dated_observations AS left_observation
    JOIN dated_observations AS right_observation
        ON right_observation.transaction_id = left_observation.transaction_id
       AND right_observation.observation_id > left_observation.observation_id
    CROSS JOIN LATERAL (
        SELECT CASE
            WHEN left_observation.source_kind = 'bank_statement'
                THEN left_observation.source_timezone
            WHEN right_observation.source_kind = 'bank_statement'
                THEN right_observation.source_timezone
            ELSE left_observation.source_timezone
        END AS source_timezone
    ) AS comparison
)
SELECT
    transaction_id,
    observation_id_1,
    observation_date_1,
    observation_id_2,
    observation_date_2,
    source_timezone
FROM inconsistent_pairs
WHERE observation_date_1 IS DISTINCT FROM observation_date_2
ORDER BY transaction_id, observation_id_1, observation_id_2;

-- Statement/SMS observations that agree on card, business date and either booked
-- or original money but are linked to different transactions. These are candidates
-- for a split caused by UTC calendar-date handling; descriptions still require review.
WITH linked_observations AS (
    SELECT
        l.transaction_id,
        o.id AS observation_id,
        o.card_id,
        o.amount,
        o.currency,
        o.original_amount,
        o.original_currency,
        o.transaction_datetime,
        o.posting_datetime,
        o.description,
        p.source_kind,
        COALESCE(
            NULLIF(p.ingestion_metadata ->> 'source_timezone', ''),
            c.timezone,
            a.timezone,
            'UTC'
        ) AS source_timezone
    FROM transaction_source_links AS l
    JOIN transaction_observations AS o
        ON o.id = l.observation_id
    JOIN source_payloads AS p
        ON p.id = o.source_payload_id
    LEFT JOIN cards AS c
        ON c.id = o.card_id
    LEFT JOIN accounts AS a
        ON a.id = c.account_id
    WHERE p.source_kind IN ('sms', 'bank_statement')
), statement_sms_split AS (
    SELECT
        statement.transaction_id AS statement_transaction_id,
        statement.observation_id AS statement_observation_id,
        sms.transaction_id AS sms_transaction_id,
        sms.observation_id AS sms_observation_id,
        statement.source_timezone,
        (
            statement.transaction_datetime
            AT TIME ZONE statement.source_timezone
        )::date AS statement_date,
        (
            COALESCE(sms.transaction_datetime, sms.posting_datetime)
            AT TIME ZONE statement.source_timezone
        )::date AS sms_date,
        statement.description AS statement_description,
        sms.description AS sms_description
    FROM linked_observations AS statement
    JOIN linked_observations AS sms
        ON statement.source_kind = 'bank_statement'
       AND sms.source_kind = 'sms'
       AND sms.card_id = statement.card_id
       AND sms.transaction_id != statement.transaction_id
       AND (
            (sms.amount = statement.amount AND sms.currency = statement.currency)
         OR (
                sms.amount = statement.original_amount
            AND sms.currency = statement.original_currency
         )
         OR (
                sms.original_amount = statement.amount
            AND sms.original_currency = statement.currency
         )
       )
)
SELECT
    statement_transaction_id,
    statement_observation_id,
    sms_transaction_id,
    sms_observation_id,
    statement_date,
    sms_date,
    source_timezone,
    statement_description,
    sms_description
FROM statement_sms_split
WHERE statement_date = sms_date
ORDER BY statement_date, statement_transaction_id, sms_transaction_id;

COMMIT;
