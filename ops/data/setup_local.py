"""Register already imported local samples; preserve existing source profiles and drafts."""

from __future__ import annotations

import os

from sqlalchemy.engine import make_url

from semaloom.app.bootstrap import build_services
from semaloom.runtime.source_validation import validate_source
from semaloom.runtime.studio_control import documents_from_bundle


def main() -> None:
    target = make_url(os.environ["SEMALOOM_META_DATABASE_URL"])
    if (
        target.host not in {"localhost", "127.0.0.1", "::1"}
        or target.database != "semaloom_sample_meta"
        or target.query
    ):
        raise ValueError("setup requires the isolated local semaloom_sample_meta database")
    services = build_services(load_data=False)
    try:
        for source_id, label, provider, variable in (
            ("sample_pg", "申报与审计样本 PostgreSQL", "postgres", "SEMALOOM_SAMPLE_DATABASE_URL"),
            ("sample_api", "审计复核状态 (模拟)", "openapi", "SEMALOOM_SAMPLE_API_URL"),
        ):
            try:
                profile = services.source_profiles.get("tenant-a", source_id)
            except KeyError:
                profile = services.source_profiles.save(
                    tenant="tenant-a",
                    actor="local-sample-setup",
                    source_id=source_id,
                    expected_revision=0,
                    label=label,
                    provider=provider,
                    binding_ref=f"env:{variable}",
                    secret_ref=None,
                    settings={"healthPath": "/health"} if provider == "openapi" else {},
                )
            status, reason = validate_source(profile, services.environment_bindings)
            services.source_profiles.set_validation("tenant-a", source_id, status)
            print(f"{source_id}: {status} ({reason})")
        draft = services.studio_drafts.load("tenant-a", "default")
        if not draft.exists:
            services.studio_drafts.save(
                "tenant-a",
                "local-sample-setup",
                "default",
                documents_from_bundle(services.bundle),
                0,
            )
        print("Local workspace ready. Existing drafts and active release are preserved.")
    finally:
        services.close()


if __name__ == "__main__":
    main()
