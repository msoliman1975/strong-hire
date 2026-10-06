# Company profiles

One JSON file per company, researched offline (see the R1 research prompt) against
`schemas/company_profile.schema.json`, reviewed, then imported with `strongctl` (AD-1).

`docs/profile-authoring.md` explains each field and the commands.

`examples/example-corp.json` is a fictional profile that shows the format. Do not import it into
a shared or production database. On a local database, import it with `--create-company`; the
company is added as inactive.
