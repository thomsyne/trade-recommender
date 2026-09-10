"""Forward-only contract evolution; retain all rows and all prior race guards."""

from importlib import import_module

from django.db import migrations

previous = import_module("market.migrations.0036_market_state_recording_boundary")
DESCRIPTOR_0120_SHA256 = "9213b548d3e6c6656805d2cf230c242926f08a42112373d7518d685384b9f7d3"
OLD_FUNCTIONS = previous.availability(previous.NEW_FUNCTIONS)
NEW_FUNCTIONS = OLD_FUNCTIONS.replace("0.11.0", "0.12.0").replace(
    "e701738372efd48e8a0bacf22e6c2956c4af624b0ad794c8289c812d8e5e1cbc", DESCRIPTOR_0120_SHA256
)

SQL = r"""
CREATE FUNCTION market_state_event_windows_valid(p jsonb, cutoff timestamptz)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE child jsonb; e jsonb; w jsonb; at timestamptz; start_at timestamptz; end_at timestamptz;
BEGIN
  IF jsonb_typeof(p)='object' THEN
    IF p->>'version'='event-state-v2' AND p->>'state'='available' THEN
      IF jsonb_typeof(p->'events') IS DISTINCT FROM 'array' OR p->>'evaluated_at' IS NULL THEN RETURN false; END IF;
      at := (p->>'evaluated_at')::timestamptz;
      IF at>cutoff THEN RETURN false; END IF;
      FOR e IN SELECT value FROM jsonb_array_elements(p->'events') LOOP
        w := e->'intraday_risk_window';
        IF jsonb_typeof(w) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
        IF e->>'time_precision'='exact' AND e->>'status' IN ('scheduled','released') THEN
          start_at := (e->>'event_at')::timestamptz - interval '30 minutes';
          end_at := (e->>'event_at')::timestamptz + interval '30 minutes';
          IF start_at IS NULL OR end_at IS NULL OR w->>'state' IS DISTINCT FROM 'available'
             OR (w->>'starts_at')::timestamptz IS DISTINCT FROM start_at
             OR (w->>'ends_at')::timestamptz IS DISTINCT FROM end_at
             OR w->'inclusive' IS DISTINCT FROM 'true'::jsonb
             OR w->>'available_at' IS NULL OR (w->>'available_at')::timestamptz>at
             OR w->>'status' IS DISTINCT FROM (CASE WHEN at<start_at THEN 'upcoming' WHEN at<=end_at THEN 'active' ELSE 'expired' END)
          THEN RETURN false; END IF;
        ELSIF w->>'state' IS DISTINCT FROM 'unavailable' THEN RETURN false;
        END IF;
      END LOOP;
    END IF;
    FOR child IN SELECT value FROM jsonb_each(p) LOOP
      IF NOT market_state_event_windows_valid(child,cutoff) THEN RETURN false; END IF;
    END LOOP;
  ELSIF jsonb_typeof(p)='array' THEN
    FOR child IN SELECT value FROM jsonb_array_elements(p) LOOP
      IF NOT market_state_event_windows_valid(child,cutoff) THEN RETURN false; END IF;
    END LOOP;
  END IF;
  RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END;
$$;

CREATE FUNCTION market_state_lifecycle_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE g jsonb; e jsonb; dep jsonb; k text; field text; b timestamptz; c timestamptz; a timestamptz; t timestamptz;
BEGIN
  IF NOT market_state_event_windows_valid(NEW.output_payload,NEW.information_cutoff) THEN
    RAISE EXCEPTION 'market_state_invalid_event_window' USING ERRCODE='23514';
  END IF;
  FOR g IN SELECT value FROM jsonb_each(NEW.output_payload->'granularities') LOOP
    FOREACH k IN ARRAY ARRAY['sweep_above','sweep_below','acceptance_above','acceptance_below'] LOOP
      e := g->'liquidity'->k;
      IF e IS NULL OR e='null'::jsonb THEN CONTINUE; END IF;
      IF jsonb_typeof(e) IS DISTINCT FROM 'object'
         OR NOT e ?& ARRAY['breach_at','confirmation_at','available_at','breach_available_at',
           'confirmation_available_at','status','expired_at','invalidated_at','terminal_available_at',
           'dependencies','level_dependencies','atr_dependencies','expiry_intervals','reason_code']
         OR coalesce(e->>'status','') NOT IN ('confirmed','invalidated','expired','unavailable')
         OR e->>'expiry_intervals' IS DISTINCT FROM '50'
         OR jsonb_typeof(e->'dependencies') IS DISTINCT FROM 'array'
         OR jsonb_typeof(e->'level_dependencies') IS DISTINCT FROM 'array'
         OR jsonb_typeof(e->'atr_dependencies') IS DISTINCT FROM 'array'
      THEN RAISE EXCEPTION 'market_state_invalid_liquidity' USING ERRCODE='23514'; END IF;
      FOREACH field IN ARRAY ARRAY['breach_at','confirmation_at','available_at','breach_available_at','confirmation_available_at'] LOOP
        IF coalesce(e->>field,'') !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$' THEN
          RAISE EXCEPTION 'market_state_invalid_liquidity' USING ERRCODE='23514';
        END IF;
      END LOOP;
      b := (e->>'breach_at')::timestamptz;
      c := (e->>'confirmation_at')::timestamptz;
      a := (e->>'available_at')::timestamptz;
      IF b IS NULL OR c IS NULL OR a IS NULL OR NOT (b<=c AND c<=a AND a<=NEW.information_cutoff)
         OR NOT (b<=(e->>'breach_available_at')::timestamptz AND (e->>'breach_available_at')::timestamptz<=a)
         OR e->>'confirmation_available_at' IS DISTINCT FROM e->>'available_at'
         OR jsonb_array_length(e->'dependencies') NOT BETWEEN 1 AND 60
         OR jsonb_array_length(e->'level_dependencies') NOT BETWEEN 1 AND 60
         OR jsonb_array_length(e->'atr_dependencies') NOT BETWEEN 1 AND 60
      THEN RAISE EXCEPTION 'market_state_liquidity_chronology' USING ERRCODE='23514'; END IF;
      IF (e->>'status'='expired') IS DISTINCT FROM (e->>'expired_at' IS NOT NULL)
         OR (e->>'status'='invalidated') IS DISTINCT FROM (e->>'invalidated_at' IS NOT NULL)
         OR (e->>'status'='confirmed') IS DISTINCT FROM (e->>'terminal_available_at' IS NULL)
      THEN RAISE EXCEPTION 'market_state_invalid_liquidity' USING ERRCODE='23514'; END IF;
      FOREACH k IN ARRAY ARRAY['expired_at','invalidated_at'] LOOP
        IF e->k <> 'null'::jsonb THEN
          t := (e->>k)::timestamptz;
          IF NOT (c<t AND t<=(e->>'terminal_available_at')::timestamptz
              AND a<=(e->>'terminal_available_at')::timestamptz
              AND (e->>'terminal_available_at')::timestamptz<=NEW.information_cutoff)
             OR e->>'terminal_available_at' IS NULL
          THEN RAISE EXCEPTION 'market_state_liquidity_chronology' USING ERRCODE='23514'; END IF;
        END IF;
      END LOOP;
      FOREACH field IN ARRAY ARRAY['dependencies','level_dependencies','atr_dependencies'] LOOP
        FOR dep IN SELECT value FROM jsonb_array_elements(e->field) LOOP
          IF NOT NEW.input_manifest @> jsonb_build_array(dep) OR jsonb_typeof(dep) IS DISTINCT FROM 'object'
             OR NOT dep ?& ARRAY['granularity','timestamp','revision','content_sha256'] THEN
            RAISE EXCEPTION 'market_state_invalid_liquidity_dependencies' USING ERRCODE='23514';
          END IF;
        END LOOP;
      END LOOP;
      IF coalesce(e->>'level_id','') !~ '^[0-9a-f]{64}$'
         OR (e ? 'acceptance_close' AND coalesce(e->>'acceptance_distance_atr','') !~ '^[0-9]+\.[0-9]{6}$')
         OR (e ? 'first_breach' AND coalesce(e->>'sweep_depth_atr','') !~ '^[0-9]+\.[0-9]{6}$') THEN
        RAISE EXCEPTION 'market_state_invalid_liquidity' USING ERRCODE='23514';
      END IF;
    END LOOP;
  END LOOP;
  RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR invalid_datetime_format OR datetime_field_overflow THEN
  RAISE EXCEPTION 'market_state_invalid_liquidity' USING ERRCODE='23514';
END;
$$;
CREATE TRIGGER market_state_lifecycle BEFORE INSERT ON market_marketstatesnapshot
FOR EACH ROW EXECUTE FUNCTION market_state_lifecycle_insert();
"""


class Migration(migrations.Migration):
    dependencies = [("market", "0036_market_state_recording_boundary")]
    operations = [
        migrations.RunSQL(
            NEW_FUNCTIONS + SQL,
            "DROP TRIGGER market_state_lifecycle ON market_marketstatesnapshot; "
            "DROP FUNCTION market_state_lifecycle_insert(); "
            "DROP FUNCTION market_state_event_windows_valid(jsonb,timestamptz); " + OLD_FUNCTIONS,
        )
    ]
