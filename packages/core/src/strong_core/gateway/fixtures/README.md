# Fake model fixtures

Used when `MODEL_PROFILE=fake` (tests and CI). See `strong_core/gateway/fake.py` for the lookup
order. Each JSON file must validate against the contract it is named after; a test checks this.
