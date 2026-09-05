\set ON_ERROR_STOP on

BEGIN TRANSACTION READ ONLY;

-- Identical SMS observations assigned to one transaction on adjacent UTC days.
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
            ) AT TIME ZONE 'UTC'
        )::date AS source_date,
        l.match_method
    FROM transaction_source_links AS l
    JOIN transaction_observations AS o
        ON o.id = l.observation_id
    JOIN source_payloads AS p
        ON p.id = o.source_payload_id
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
    a.amount,
    a.currency,
    a.merchant_key
FROM sms AS a
JOIN sms AS b
    ON b.transaction_id = a.transaction_id
   AND b.observation_id > a.observation_id
   AND b.amount = a.amount
   AND b.currency = a.currency
   AND b.merchant_key = a.merchant_key
   AND abs(b.source_date - a.source_date) = 1
ORDER BY a.transaction_id, a.source_date, a.observation_id;

-- Transactions whose linked observations disagree on the business transaction day.
-- transaction_datetime is authoritative; posting_datetime is used only as fallback.
WITH dated_observations AS (
    SELECT
        l.transaction_id,
        o.id AS observation_id,
        (
            COALESCE(o.transaction_datetime, o.posting_datetime)
            AT TIME ZONE 'UTC'
        )::date AS observation_date
    FROM transaction_source_links AS l
    JOIN transaction_observations AS o
        ON o.id = l.observation_id
    WHERE o.transaction_datetime IS NOT NULL
       OR o.posting_datetime IS NOT NULL
), inconsistent AS (
    SELECT transaction_id
    FROM dated_observations
    GROUP BY transaction_id
    HAVING count(DISTINCT observation_date) > 1
)
SELECT
    d.transaction_id,
    array_agg(d.observation_id ORDER BY d.observation_id) AS observation_ids,
    array_agg(d.observation_date ORDER BY d.observation_id) AS observation_dates
FROM dated_observations AS d
JOIN inconsistent AS i
    ON i.transaction_id = d.transaction_id
GROUP BY d.transaction_id
ORDER BY d.transaction_id;

COMMIT;
