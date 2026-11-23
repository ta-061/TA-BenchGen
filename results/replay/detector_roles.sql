-- Load after paper_cohort.sql on the read-only results database.
CREATE TEMP VIEW paper_role_target AS
SELECT p.ta_id, p.defect_id, p.class_id, t.target_id, t.role
FROM paper_defect p JOIN label_target t USING (ta_id, defect_id)
WHERE CASE WHEN p.use_public THEN t.is_public ELSE t.is_approved END;

-- A flaw contributes at most once per role and detector. A missing output stays NULL.
CREATE TEMP VIEW paper_role_result AS
SELECT t.ta_id, t.defect_id, t.role, r.method_id, max(r.hits) AS hits
FROM paper_role_target t JOIN v_target_result r USING (target_id)
GROUP BY t.ta_id, t.defect_id, t.role, r.method_id;

CREATE TEMP VIEW paper_detector_summary AS
WITH defective AS (
    SELECT DISTINCT ta_id FROM paper_defect
), runs AS (
    SELECT m.method_id, count(*) AS selected_tas, count(r.total) AS tas_with_output,
           count(*) FILTER (WHERE r.status = 'partial') AS partial_tas,
           sum(r.total) AS defective_reports
    FROM method m CROSS JOIN defective d
    LEFT JOIN v_ta_method r ON r.ta_id = d.ta_id AND r.method_id = m.method_id
    GROUP BY m.method_id
), positions AS (
    SELECT method_id,
           count(*) FILTER (WHERE role = 'protection' AND hits > 0) AS protection_matches,
           count(hits) FILTER (WHERE role = 'protection') AS protection_observed,
           count(*) FILTER (WHERE role = 'effect' AND hits > 0) AS effect_matches,
           count(hits) FILTER (WHERE role = 'effect') AS effect_observed
    FROM paper_role_result GROUP BY method_id
)
SELECT r.*, coalesce(p.protection_matches, 0) AS protection_matches,
       coalesce(p.protection_observed, 0) AS protection_observed,
       coalesce(p.effect_matches, 0) AS effect_matches,
       coalesce(p.effect_observed, 0) AS effect_observed
FROM runs r LEFT JOIN positions p USING (method_id);
