PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;

CREATE TABLE snapshot (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    measured_input_commit TEXT NOT NULL,
    llm_status_utc TEXT NOT NULL
);

-- A control owns its source name. A defective input points to its control.
CREATE TABLE ta (
    ta_id TEXT PRIMARY KEY NOT NULL,
    normal_id TEXT REFERENCES ta(ta_id),
    base_name TEXT UNIQUE,
    case_id TEXT UNIQUE,
    scope TEXT NOT NULL CHECK (scope IN ('current', 'rejected', 'retired_normal')),
    review TEXT NOT NULL CHECK (review IN ('normal','approved','partially_approved','rejected','unreviewed','in_review')),
    input_path TEXT NOT NULL UNIQUE,
    benchmark_path TEXT UNIQUE,
    CHECK ((scope = 'retired_normal') = (benchmark_path IS NULL)),
    CHECK ((scope = 'rejected') = (review = 'rejected')),
    CHECK ((normal_id IS NULL AND base_name IS NOT NULL AND case_id IS NULL AND review = 'normal')
        OR (normal_id IS NOT NULL AND normal_id <> ta_id AND base_name IS NULL AND
            case_id IS NOT NULL AND review <> 'normal' AND scope <> 'retired_normal'))
);
CREATE TABLE source_file (
    ta_id TEXT NOT NULL REFERENCES ta,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    PRIMARY KEY (ta_id, path)
) WITHOUT ROWID;
CREATE TABLE method (
    method_id TEXT PRIMARY KEY NOT NULL,
    display_name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL UNIQUE,
    source_directory TEXT NOT NULL
);
CREATE TABLE defect_class (
    class_id TEXT PRIMARY KEY NOT NULL,
    sort_order INTEGER NOT NULL UNIQUE
);
CREATE TABLE method_class (
    method_id TEXT NOT NULL REFERENCES method,
    class_id TEXT NOT NULL REFERENCES defect_class,
    PRIMARY KEY (method_id, class_id)
) WITHOUT ROWID;
CREATE TABLE defect (
    ta_id TEXT NOT NULL REFERENCES ta,
    defect_id TEXT NOT NULL,
    class_id TEXT NOT NULL REFERENCES defect_class,
    decision TEXT NOT NULL CHECK (decision IN ('approved','rejected','unreviewed','in_review')),
    order_example TEXT,
    reason TEXT NOT NULL,
    PRIMARY KEY (ta_id, defect_id)
) WITHOUT ROWID;
CREATE TABLE label_target (
    target_id INTEGER PRIMARY KEY,
    ta_id TEXT NOT NULL,
    defect_id TEXT NOT NULL,
    path TEXT NOT NULL,
    first_line INTEGER NOT NULL CHECK (first_line > 0),
    last_line INTEGER NOT NULL CHECK (last_line >= first_line),
    role TEXT NOT NULL CHECK (role IN ('effect','protection')),
    function_name TEXT NOT NULL,
    is_public INTEGER NOT NULL CHECK (is_public IN (0,1)),
    is_approved INTEGER NOT NULL CHECK (is_approved IN (0,1)),
    CHECK (is_public OR is_approved),
    UNIQUE (ta_id, defect_id, role, path, first_line, last_line, function_name),
    FOREIGN KEY (ta_id, defect_id) REFERENCES defect,
    FOREIGN KEY (ta_id, path) REFERENCES source_file
);
CREATE INDEX target_by_file ON label_target(ta_id, path, first_line, last_line);

-- One adopted measurement per TA and method in this snapshot.
CREATE TABLE analysis_run (
    ta_id TEXT NOT NULL REFERENCES ta,
    method_id TEXT NOT NULL REFERENCES method,
    status TEXT NOT NULL CHECK (status IN ('completed','partial','running','pending','failed')),
    output_path TEXT UNIQUE,
    CHECK ((status IN ('completed','partial')) = (output_path IS NOT NULL)),
    PRIMARY KEY (ta_id, method_id)
) WITHOUT ROWID;
CREATE TABLE native_rule (
    method_id TEXT NOT NULL REFERENCES method,
    rule_name TEXT NOT NULL,
    class_id TEXT,
    PRIMARY KEY (method_id, rule_name),
    FOREIGN KEY (method_id, class_id) REFERENCES method_class
) WITHOUT ROWID;
CREATE TABLE report (
    ta_id TEXT NOT NULL,
    method_id TEXT NOT NULL,
    report_ref TEXT NOT NULL,
    PRIMARY KEY (ta_id, method_id, report_ref),
    FOREIGN KEY (ta_id, method_id) REFERENCES analysis_run
) WITHOUT ROWID;
CREATE TABLE report_rule (
    ta_id TEXT NOT NULL,
    method_id TEXT NOT NULL,
    report_ref TEXT NOT NULL,
    rule_name TEXT NOT NULL,
    is_primary INTEGER NOT NULL CHECK (is_primary IN (0,1)),
    PRIMARY KEY (ta_id, method_id, report_ref, rule_name),
    FOREIGN KEY (ta_id, method_id, report_ref) REFERENCES report,
    FOREIGN KEY (method_id, rule_name) REFERENCES native_rule
) WITHOUT ROWID;
CREATE UNIQUE INDEX one_primary_rule ON report_rule(ta_id, method_id, report_ref) WHERE is_primary = 1;
CREATE TABLE report_location (
    ta_id TEXT NOT NULL,
    method_id TEXT NOT NULL,
    report_ref TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    path TEXT NOT NULL,
    first_line INTEGER NOT NULL CHECK (first_line > 0),
    last_line INTEGER NOT NULL CHECK (last_line >= first_line),
    first_column INTEGER,
    last_column INTEGER,
    PRIMARY KEY (ta_id, method_id, report_ref, ordinal),
    FOREIGN KEY (ta_id, method_id, report_ref) REFERENCES report,
    FOREIGN KEY (ta_id, path) REFERENCES source_file
) WITHOUT ROWID;

CREATE VIEW v_ta AS
SELECT t.ta_id, t.scope, t.review, COALESCE(t.normal_id, t.ta_id) AS normal_id, t.case_id,
       COALESCE(t.base_name, n.base_name) AS base_name,
       COALESCE(t.base_name, n.base_name) || '_' || CASE WHEN t.normal_id IS NULL THEN '正常' ELSE
         (SELECT group_concat(label_name, '+') FROM (
             SELECT d.class_id || COALESCE('(' || d.order_example || ')','') AS label_name
             FROM defect d WHERE d.ta_id = t.ta_id ORDER BY CAST(substr(d.defect_id,2) AS INTEGER)
         )) END AS display_name, t.input_path, t.benchmark_path
FROM ta t LEFT JOIN ta n ON n.ta_id = t.normal_id;

CREATE VIEW v_primary_rule AS
SELECT rr.ta_id, rr.method_id, rr.report_ref, rr.rule_name, nr.class_id AS reported_class
FROM report_rule rr JOIN native_rule nr USING (method_id, rule_name) WHERE rr.is_primary = 1;

-- A report can cover several primary locations. Each report/target pair appears once.
CREATE VIEW v_match AS
SELECT DISTINCT l.ta_id, l.method_id, l.report_ref, t.target_id, t.defect_id,
       t.is_public, t.is_approved, d.class_id AS label_class, pr.reported_class,
       d.class_id = pr.reported_class AS same_class
FROM report_location l JOIN label_target t ON t.ta_id = l.ta_id AND t.path = l.path
     AND l.first_line <= t.last_line AND t.first_line <= l.last_line
JOIN defect d ON d.ta_id = t.ta_id AND d.defect_id = t.defect_id
JOIN v_primary_rule pr ON pr.ta_id = l.ta_id AND pr.method_id = l.method_id AND pr.report_ref = l.report_ref;

CREATE VIEW v_report AS
WITH hits AS (
    SELECT ta_id, method_id, report_ref, max(is_public) AS pub, max(is_approved) AS app,
           max(is_public * same_class) AS pub_same, max(is_approved * same_class) AS app_same
    FROM v_match GROUP BY ta_id, method_id, report_ref
)
SELECT p.*, COALESCE(h.pub,0) AS within_public, COALESCE(h.pub_same,0) AS same_public,
       COALESCE(h.app,0) AS within_approved, COALESCE(h.app_same,0) AS same_approved
FROM v_primary_rule p LEFT JOIN hits h USING (ta_id, method_id, report_ref);

CREATE VIEW v_defect_result AS
WITH hits AS (
    SELECT ta_id, method_id, defect_id,
           count(DISTINCT CASE WHEN is_public THEN report_ref END) AS pub,
           count(DISTINCT CASE WHEN is_public AND same_class THEN report_ref END) AS pub_same,
           count(DISTINCT CASE WHEN is_approved THEN report_ref END) AS app,
           count(DISTINCT CASE WHEN is_approved AND same_class THEN report_ref END) AS app_same
    FROM v_match GROUP BY ta_id, method_id, defect_id
)
SELECT d.ta_id, d.defect_id, d.class_id, d.decision, r.method_id, r.status,
       r.output_path IS NOT NULL AS observed, mc.class_id IS NOT NULL AS comparable,
       CASE WHEN r.output_path IS NOT NULL THEN COALESCE(h.pub,0) END AS within_public,
       CASE WHEN r.output_path IS NOT NULL AND mc.class_id IS NOT NULL THEN COALESCE(h.pub_same,0) END AS same_public,
       CASE WHEN r.output_path IS NOT NULL AND d.decision = 'approved' THEN COALESCE(h.app,0) END AS within_approved,
       CASE WHEN r.output_path IS NOT NULL AND d.decision = 'approved' AND mc.class_id IS NOT NULL
            THEN COALESCE(h.app_same,0) END AS same_approved
FROM defect d JOIN analysis_run r USING (ta_id)
LEFT JOIN method_class mc ON mc.method_id = r.method_id AND mc.class_id = d.class_id
LEFT JOIN hits h ON h.ta_id = d.ta_id AND h.defect_id = d.defect_id AND h.method_id = r.method_id;

CREATE VIEW v_target_result AS
WITH hits AS (
    SELECT target_id, method_id, count(*) AS hits, sum(same_class) AS same
    FROM v_match GROUP BY target_id, method_id
)
SELECT t.*, d.class_id, d.decision, r.method_id, r.status,
       CASE WHEN r.output_path IS NOT NULL THEN COALESCE(h.hits,0) END AS hits,
       CASE WHEN r.output_path IS NOT NULL AND mc.class_id IS NOT NULL THEN COALESCE(h.same,0) END AS same
FROM label_target t JOIN defect d USING (ta_id, defect_id) JOIN analysis_run r USING (ta_id)
LEFT JOIN method_class mc ON mc.method_id = r.method_id AND mc.class_id = d.class_id
LEFT JOIN hits h ON h.target_id = t.target_id AND h.method_id = r.method_id;

CREATE VIEW v_ta_method AS
WITH findings AS (
    SELECT ta_id, method_id, count(*) AS total, sum(within_public) AS pub, sum(same_public) AS pub_same,
           sum(within_approved) AS app, sum(same_approved) AS app_same
    FROM v_report GROUP BY ta_id, method_id
), labels AS (
    SELECT ta_id, method_id, count(*) AS pub, sum(decision = 'approved') AS app,
           sum(comparable) AS pub_comp, sum(comparable AND decision = 'approved') AS app_comp,
           sum(within_public > 0) AS pub_hit, sum(within_approved > 0) AS app_hit,
           sum(same_public > 0) AS pub_same, sum(same_approved > 0) AS app_same
    FROM v_defect_result GROUP BY ta_id, method_id
)
SELECT r.ta_id, r.method_id, r.status, r.output_path,
       CASE WHEN r.output_path IS NOT NULL THEN COALESCE(f.total,0) END AS total,
       CASE WHEN r.output_path IS NOT NULL AND l.pub > 0 THEN COALESCE(f.pub,0) END AS within_public,
       CASE WHEN r.output_path IS NOT NULL AND l.pub_comp > 0 THEN COALESCE(f.pub_same,0) END AS same_public,
       CASE WHEN r.output_path IS NOT NULL AND l.app > 0 THEN COALESCE(f.app,0) END AS within_approved,
       CASE WHEN r.output_path IS NOT NULL AND l.app_comp > 0 THEN COALESCE(f.app_same,0) END AS same_approved,
       COALESCE(l.pub,0) AS labels_public, COALESCE(l.pub_comp,0) AS comparable_public,
       l.pub_hit AS labels_hit_public, l.pub_same AS labels_same_public,
       COALESCE(l.app,0) AS labels_approved, COALESCE(l.app_comp,0) AS comparable_approved,
       l.app_hit AS labels_hit_approved, l.app_same AS labels_same_approved
FROM analysis_run r LEFT JOIN findings f USING (ta_id, method_id) LEFT JOIN labels l USING (ta_id, method_id);

-- Counts by the tool's reported class. 'unmapped' includes native rules without a four-class mapping.
CREATE VIEW v_ta_method_class AS
WITH vocabulary AS (
    SELECT method_id, class_id FROM method_class UNION ALL SELECT method_id, 'unmapped' FROM method
), findings AS (
    SELECT ta_id, method_id, COALESCE(reported_class,'unmapped') AS class_id, count(*) AS total,
           sum(within_public) AS pub, sum(same_public) AS pub_same,
           sum(within_approved) AS app, sum(same_approved) AS app_same
    FROM v_report GROUP BY ta_id, method_id, COALESCE(reported_class,'unmapped')
), labels AS (
    SELECT ta_id, class_id, count(*) AS pub, sum(decision = 'approved') AS app
    FROM defect GROUP BY ta_id, class_id
)
SELECT r.ta_id, r.method_id, v.class_id, r.status,
       CASE WHEN r.total IS NOT NULL THEN COALESCE(f.total,0) END AS total,
       CASE WHEN r.within_public IS NOT NULL THEN COALESCE(f.pub,0) END AS within_public,
       CASE WHEN r.total IS NOT NULL AND l.pub > 0 THEN COALESCE(f.pub_same,0) END AS same_public,
       CASE WHEN r.within_approved IS NOT NULL THEN COALESCE(f.app,0) END AS within_approved,
       CASE WHEN r.total IS NOT NULL AND l.app > 0 THEN COALESCE(f.app_same,0) END AS same_approved
FROM v_ta_method r JOIN vocabulary v USING (method_id)
LEFT JOIN findings f ON f.ta_id = r.ta_id AND f.method_id = r.method_id AND f.class_id = v.class_id
LEFT JOIN labels l ON l.ta_id = r.ta_id AND l.class_id = v.class_id;

CREATE VIEW v_method_summary AS
SELECT r.method_id, count(*) AS ta_count, count(r.total) AS with_output,
       sum(r.status = 'partial') AS partial, sum(r.total IS NULL) AS without_output,
       sum(CASE WHEN t.normal_id IS NULL THEN r.total END) AS control_reports,
       sum(CASE WHEN t.normal_id IS NOT NULL THEN r.total END) AS defective_reports, sum(r.total) AS total_reports,
       sum(r.within_approved) AS reports_at_approved, sum(r.same_approved) AS reports_same_approved,
       sum(CASE WHEN r.total IS NOT NULL THEN r.labels_approved END) AS approved_labels_evaluated,
       sum(r.labels_hit_approved) AS approved_labels_hit,
       sum(CASE WHEN r.total IS NOT NULL THEN r.comparable_approved END) AS class_comparable_labels,
       sum(r.labels_same_approved) AS approved_labels_same
FROM v_ta_method r JOIN ta t USING (ta_id) WHERE t.scope = 'current' GROUP BY r.method_id;

-- The class is that of the injection, independent of the classification a tool reported.
CREATE VIEW v_class_summary AS
WITH grouped AS (
    SELECT d.method_id, d.class_id, count(*) AS registered, sum(d.observed) AS measured,
           sum(d.within_approved > 0) AS hit, sum(d.observed * d.comparable) AS comparable,
           sum(d.same_approved > 0) AS same
    FROM v_defect_result d JOIN ta t USING (ta_id)
    WHERE t.scope = 'current' AND d.decision = 'approved' GROUP BY d.method_id, d.class_id
)
SELECT m.method_id, c.class_id, COALESCE(g.registered,0) AS approved_labels,
       COALESCE(g.measured,0) AS labels_evaluated, g.hit AS labels_hit,
       COALESCE(g.comparable,0) AS comparable_labels, g.same AS labels_same
FROM method m CROSS JOIN defect_class c
LEFT JOIN grouped g ON g.method_id = m.method_id AND g.class_id = c.class_id;
