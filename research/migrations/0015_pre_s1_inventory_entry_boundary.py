from datetime import time, timedelta
from zoneinfo import ZoneInfo

from django.db import migrations


def _legacy_expected_entry(confirmation):
    local = confirmation.astimezone(ZoneInfo("America/New_York"))
    if local.weekday() == 4 and local.time().replace(tzinfo=None) == time(17):
        return (local + timedelta(days=2)).replace(hour=17).astimezone(confirmation.tzinfo)
    return confirmation


def assert_existing_entry_boundaries(apps, schema_editor):
    Transition = apps.get_model("research", "SetupTransition")
    Evaluation = apps.get_model("research", "EntryEligibilityEvaluation")
    Observation = apps.get_model("market", "HistoricalTimestampObservation")
    Candle = apps.get_model("market", "Candle")
    CandleConflict = apps.get_model("market", "CandleConflict")
    confirmations = {
        setup_id: effective_at
        for setup_id, effective_at in Transition.objects.filter(
            from_state="TRIGGER_PENDING", to_state="CONFIRMED", book_identity=""
        ).values_list("setup_id", "effective_at")
    }

    def expected_entry(setup, confirmation):
        registration = getattr(setup.dataset_version, "registration", None)
        contract = getattr(registration, "data_contract", None) if registration else None
        if contract is None:
            return _legacy_expected_entry(confirmation)
        timestamp = (
            Observation.objects.filter(
                inventory__chunk__plan=contract.discovery_registration.plan,
                inventory__chunk__instrument_id=setup.instrument_id,
                inventory__chunk__granularity="H1",
                timestamp__gte=confirmation,
            )
            .order_by("timestamp")
            .values_list("timestamp", flat=True)
            .first()
        )
        candle = Candle.objects.filter(
            dataset_version_id=setup.dataset_version_id,
            instrument_id=setup.instrument_id,
            granularity="H1",
            timestamp=timestamp,
            complete=True,
            ingestion_run__dataset_version_id=setup.dataset_version_id,
            ingestion_run__status="succeeded",
        ).first()
        if (
            timestamp is None
            or candle is None
            or CandleConflict.objects.filter(
                dataset_version_id=setup.dataset_version_id, existing_candle_id=candle.pk
            ).exists()
        ):
            return None
        return timestamp

    setup_ids = set(
        Transition.objects.filter(from_state="CONFIRMED").values_list("setup_id", flat=True)
    )
    setup_ids.update(
        Evaluation.objects.filter(decision="ENTRY_PENDING").values_list("setup_id", flat=True)
    )
    Setup = apps.get_model("research", "SetupEvent")
    setups = {
        setup.pk: setup
        for setup in Setup.objects.filter(pk__in=setup_ids).select_related(
            "dataset_version__registration__data_contract__discovery_registration__plan"
        )
    }
    for transition in Transition.objects.filter(from_state="CONFIRMED"):
        confirmation = confirmations.get(transition.setup_id)
        expected = (
            expected_entry(setups[transition.setup_id], confirmation) if confirmation else None
        )
        if expected is None or transition.effective_at != expected:
            raise RuntimeError("existing book transition is not at the sealed entry successor")
    for evaluation in Evaluation.objects.filter(decision="ENTRY_PENDING"):
        confirmation = confirmations.get(evaluation.setup_id)
        expected = (
            expected_entry(setups[evaluation.setup_id], confirmation) if confirmation else None
        )
        if expected is None or evaluation.entry_timestamp != expected:
            raise RuntimeError("existing entry evaluation is not at the sealed entry successor")


FORWARD_SQL = """
CREATE OR REPLACE FUNCTION research_confirmation_entry_boundary(setup_key bigint)
RETURNS timestamptz AS $$
DECLARE
    confirmation_at timestamptz;
    confirmation_local timestamp;
    setup_dataset bigint;
    setup_instrument bigint;
    contract_key bigint;
    discovery_plan_key bigint;
    expected_entry timestamptz;
BEGIN
    SELECT transition.effective_at, setup.dataset_version_id, setup.instrument_id
      INTO STRICT confirmation_at, setup_dataset, setup_instrument
      FROM research_setuptransition transition
      JOIN research_setupevent setup ON setup.id = transition.setup_id
     WHERE transition.setup_id = setup_key
       AND transition.from_state = 'TRIGGER_PENDING'
       AND transition.to_state = 'CONFIRMED'
       AND transition.book_identity = '';

    SELECT registration.data_contract_id
      INTO contract_key
      FROM market_datasetregistration registration
     WHERE registration.dataset_version_id = setup_dataset;

    IF contract_key IS NOT NULL THEN
        SELECT discovery_registration.plan_id
          INTO STRICT discovery_plan_key
          FROM market_historicaldatacontract contract
          JOIN market_historicaldiscoveryregistration discovery_registration
            ON discovery_registration.id = contract.discovery_registration_id
         WHERE contract.id = contract_key;

        SELECT observation.timestamp
          INTO STRICT expected_entry
          FROM market_historicaltimestampobservation observation
          JOIN market_historicaltimestampinventory inventory
            ON inventory.id = observation.inventory_id
          JOIN market_historicaldiscoverychunk chunk ON chunk.id = inventory.chunk_id
         WHERE chunk.plan_id = discovery_plan_key
           AND chunk.instrument_id = setup_instrument
           AND chunk.granularity = 'H1'
           AND observation.timestamp >= confirmation_at
         ORDER BY observation.timestamp
         LIMIT 1;
        IF NOT EXISTS (
            SELECT 1
              FROM market_candle candle
              JOIN market_ingestionrun ingestion ON ingestion.id = candle.ingestion_run_id
              LEFT JOIN market_candleconflict conflict
                ON conflict.dataset_version_id = setup_dataset
               AND conflict.existing_candle_id = candle.id
             WHERE candle.dataset_version_id = setup_dataset
               AND candle.instrument_id = setup_instrument
               AND candle.granularity = 'H1'
               AND candle.timestamp = expected_entry
               AND candle.complete
               AND ingestion.dataset_version_id = setup_dataset
               AND ingestion.status = 'succeeded'
               AND conflict.id IS NULL
        ) THEN
            RAISE EXCEPTION 'sealed H1 entry successor lacks conflict-free registered evidence';
        END IF;
        RETURN expected_entry;
    END IF;

    confirmation_local := confirmation_at AT TIME ZONE 'America/New_York';
    IF extract(isodow FROM confirmation_local) = 5
       AND confirmation_local::time = time '17:00:00' THEN
        RETURN (confirmation_local + interval '2 days') AT TIME ZONE 'America/New_York';
    END IF;
    RETURN confirmation_at;
EXCEPTION WHEN NO_DATA_FOUND THEN
    RAISE EXCEPTION 'entry record requires one global confirmed transition and sealed successor';
END;
$$ LANGUAGE plpgsql STABLE;
"""


REVERSE_SQL = """
CREATE OR REPLACE FUNCTION research_confirmation_entry_boundary(setup_key bigint)
RETURNS timestamptz AS $$
DECLARE
    confirmation_at timestamptz;
    confirmation_local timestamp;
BEGIN
    SELECT effective_at INTO STRICT confirmation_at
      FROM research_setuptransition
     WHERE setup_id = setup_key
       AND from_state = 'TRIGGER_PENDING'
       AND to_state = 'CONFIRMED'
       AND book_identity = '';
    confirmation_local := confirmation_at AT TIME ZONE 'America/New_York';
    IF extract(isodow FROM confirmation_local) = 5
       AND confirmation_local::time = time '17:00:00' THEN
        RETURN (confirmation_local + interval '2 days') AT TIME ZONE 'America/New_York';
    END IF;
    RETURN confirmation_at;
EXCEPTION WHEN NO_DATA_FOUND THEN
    RAISE EXCEPTION 'entry record requires one global confirmed transition';
END;
$$ LANGUAGE plpgsql STABLE;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("market", "0027_gate8i_final_dataset_acceptance"),
        ("research", "0014_enforce_entry_boundary"),
    ]

    operations = [
        migrations.RunPython(assert_existing_entry_boundaries, migrations.RunPython.noop),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
