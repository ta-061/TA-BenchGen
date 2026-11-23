-- Apply to a read-only benchmark-results.db connection. The views are session-local.
CREATE TEMP VIEW paper_defect AS
SELECT d.ta_id, d.defect_id, d.class_id, t.normal_id,
       t.case_id = 'case_e264a169df23d680' AS use_public
FROM defect d JOIN ta t USING (ta_id)
WHERE t.scope = 'current' AND (
    (t.review = 'approved' AND d.decision = 'approved')
    OR (t.case_id = 'case_c4cb059bfbd14ca1' AND d.decision = 'approved')
    OR (t.case_id = 'case_e264a169df23d680' AND d.class_id = 'ORDER'
        AND d.order_example IN ('C1', 'C2'))
);

-- A control shared by several variants contributes one measurement.
CREATE TEMP VIEW paper_ta AS
SELECT ta_id FROM paper_defect UNION SELECT normal_id FROM paper_defect;

-- The published locations are used for the two PKCS#11 case-study labels.
-- For generated cases, use the locations saved at human approval.
CREATE TEMP VIEW paper_defect_result AS
SELECT p.ta_id, p.defect_id, p.class_id, r.method_id,
       CASE WHEN p.use_public THEN r.within_public ELSE r.within_approved END AS location_hits,
       CASE WHEN p.use_public THEN r.same_public ELSE r.same_approved END AS class_hits
FROM paper_defect p JOIN v_defect_result r USING (ta_id, defect_id);

CREATE TEMP VIEW paper_match AS
SELECT m.*
FROM paper_defect p JOIN v_match m USING (ta_id, defect_id)
WHERE CASE WHEN p.use_public THEN m.is_public ELSE m.is_approved END;

CREATE TEMP VIEW paper_class_summary AS
SELECT method_id, class_id, count(*) AS selected_labels,
       count(location_hits) AS observed_labels, sum(location_hits > 0) AS location_matches,
       count(class_hits) AS comparable_labels, sum(class_hits > 0) AS location_class_matches
FROM paper_defect_result GROUP BY method_id, class_id;

-- Aggregate outputs, reported classes, and distinct benchmark labels at their own grains.
CREATE TEMP VIEW paper_method_summary AS
WITH runs AS (
    SELECT r.method_id, count(*) AS selected_tas, count(r.total) AS tas_with_output,
           count(r.total) FILTER (WHERE t.normal_id IS NULL) AS controls_with_output,
           count(r.total) FILTER (WHERE t.normal_id IS NOT NULL) AS defective_tas_with_output,
           sum(r.status = 'partial') AS partial_tas,
           sum(r.total) FILTER (WHERE t.normal_id IS NULL) AS control_reports,
           sum(r.total) FILTER (WHERE t.normal_id IS NOT NULL) AS defective_reports
    FROM paper_ta p JOIN ta t USING (ta_id) JOIN v_ta_method r USING (ta_id) GROUP BY r.method_id
), reported AS (
    SELECT method_id, sum(total) FILTER (WHERE class_id = 'IVW') AS reported_ivw,
           sum(total) FILTER (WHERE class_id = 'UDO') AS reported_udo,
           sum(total) FILTER (WHERE class_id = 'DUS') AS reported_dus,
           sum(total) FILTER (WHERE class_id = 'unmapped') AS reported_unmapped
    FROM paper_ta JOIN v_ta_method_class USING (ta_id) GROUP BY method_id
), labels AS (
    SELECT method_id, sum(selected_labels) AS selected_labels, sum(observed_labels) AS observed_labels,
           sum(location_matches) AS location_matches, sum(comparable_labels) AS comparable_labels,
           sum(location_class_matches) AS location_class_matches
    FROM paper_class_summary GROUP BY method_id
)
SELECT runs.*, reported_ivw, reported_udo, reported_dus, reported_unmapped,
       selected_labels, observed_labels, location_matches, comparable_labels, location_class_matches
FROM runs JOIN reported USING (method_id) JOIN labels USING (method_id);
