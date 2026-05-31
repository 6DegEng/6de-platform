# Legacy Status Map

How legacy xlsx status strings map to the platform's 10-value status enum.

## Status Mapping

| Legacy Value       | Platform Enum     | Notes                              |
|--------------------|-------------------|------------------------------------|
| Active             | `active`          | Direct match                       |
| On Hold            | `on_hold`         | Direct match                       |
| Completed          | `completed`       | Direct match                       |
| Complete           | `completed`       | Synonym                            |
| Closed             | `completed`       | Treated as completed               |
| Prospect           | `prospect`        | Direct match                       |
| Archived           | `archived`        | Direct match                       |
| Archive            | `archived`        | Synonym                            |
| Drafting           | `drafting`        | Session 3b status                  |
| AHJ/Permitting     | `ahj_permitting`  | Session 3b status                  |
| Permitting         | `ahj_permitting`  | Abbreviated form                   |
| Inspection         | `inspection`      | Session 3b status                  |
| Revisions          | `revisions`       | Session 3b status                  |
| Cancelled          | `cancelled`       | Session 3b status                  |
| Canceled           | `cancelled`       | American spelling                  |
| *(empty/missing)*  | `active`          | Default when no status provided    |

## Priority Mapping

| Legacy Value | Platform Enum | Notes                                      |
|--------------|---------------|--------------------------------------------|
| Low          | `low`         | Direct match                               |
| Medium       | `normal`      | Platform uses "normal" not "medium"         |
| Normal       | `normal`      | Direct match                               |
| High         | `high`        | Direct match                               |
| Urgent       | `urgent`      | Direct match                               |
| On Hold      | `normal`      | "On Hold" is a status, not a priority level |

## Lifecycle Buckets

Mature Monday-style trackers group rows into lifecycle buckets that
drive board sections. The mapping from platform status to bucket:

| Bucket     | Statuses                                                    |
|------------|-------------------------------------------------------------|
| PROPOSED   | `prospect`                                                  |
| ACTIVE     | `active`, `drafting`, `ahj_permitting`, `inspection`, `revisions` |
| STAND BY   | `on_hold`                                                   |
| FINISHED   | `completed`                                                 |
| LOST       | `cancelled`                                                 |
| ARCHIVED   | `archived`                                                  |

The mapping is implemented in `modules/status_colors.py` as `STATUS_TO_BUCKET`.
The `lifecycle_bucket` value is not persisted on the `projects` table — it is
computed at read time in `streamlit_app/components/project_grid.py`
(`projects_to_dataframe`) and surfaces in the AgGrid table view as a sortable
/ groupable column.
