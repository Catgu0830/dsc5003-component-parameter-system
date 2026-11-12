-- Schema names match backend/schema.sql. Bind user input via placeholders in application code.
-- A regular user must additionally constrain c.owner_id to the authenticated user id.

-- Published components and canonical manufacturer.
SELECT c.component_id,c.model,c.category,m.name AS manufacturer
FROM components c JOIN manufacturers m USING(manufacturer_id)
WHERE c.owner_id=:current_user_id AND c.model LIKE :model_pattern;

-- Multiple numeric filters: values are already normalized to SI base units.
SELECT c.component_id,c.model
FROM components c
WHERE c.owner_id=:current_user_id
AND EXISTS(SELECT 1 FROM parameters p WHERE p.component_id=c.component_id
           AND p.parameter_name='voltage' AND p.value_num BETWEEN 3.3 AND 5)
AND EXISTS(SELECT 1 FROM parameters p WHERE p.component_id=c.component_id
           AND p.parameter_name='resistance' AND p.value_num BETWEEN 1000 AND 10000);

-- Audit backlog (admin/auditor only).
SELECT task_id,user_id,source_type,created_time
FROM tasks WHERE status='success' AND review_status='pending' AND deleted=0;

-- Provenance and published revisions for one component.
SELECT ct.revision,t.task_id,t.source_type,t.original_filename,a.action,a.comment,a.audit_time
FROM component_tasks ct JOIN tasks t USING(task_id)
JOIN audit_logs a USING(task_id)
WHERE ct.component_id=:component_id ORDER BY ct.revision;
