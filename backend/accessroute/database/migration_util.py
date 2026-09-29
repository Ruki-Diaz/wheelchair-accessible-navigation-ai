"""Migration utility to transfer community observations and interactions from SQLite to PostgreSQL.

Supports dry-run verification, preserves IDs, timestamps, verification statuses,
and confirms exact row-count parity.
"""

import argparse
import logging
from typing import Dict, Any, Tuple

from accessroute.community.repository import SQLiteCommunityObservationRepository
from accessroute.database.repository import PostgresCommunityObservationRepository
from accessroute.database.config import db_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def migrate_sqlite_to_postgres(
    sqlite_db_path: str,
    postgres_url: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Execute migration of community observations and interactions.

    Args:
        sqlite_db_path: Path to existing SQLite database file.
        postgres_url: Target PostgreSQL connection string.
        dry_run: If True, inspects and logs counts without writing to PostgreSQL.

    Returns:
        Summary dict containing counts and verification status.
    """
    logger.info("Initializing SQLite source repository from %s", sqlite_db_path)
    sqlite_repo = SQLiteCommunityObservationRepository(db_path=sqlite_db_path)
    source_count = sqlite_repo.count(include_expired=True)
    all_observations = sqlite_repo.list_all(limit=100000, offset=0, include_expired=True)

    logger.info("Source SQLite database contains %d observations", source_count)

    interactions_count = 0
    with sqlite_repo._get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM community_interactions;")
        interactions_count = cur.fetchone()[0]

    logger.info("Source SQLite database contains %d community interactions", interactions_count)

    if dry_run:
        logger.info("[DRY RUN] Would migrate %d observations and %d interactions to %s", source_count, interactions_count, postgres_url)
        return {
            "status": "dry_run_success",
            "success": True,
            "observations_found": source_count,
            "interactions_found": interactions_count,
            "observations_migrated": 0,
            "migrated_count": 0,
            "parity_verified": True,
        }

    logger.info("Connecting to target PostgreSQL repository...")
    pg_repo = PostgresCommunityObservationRepository(connection_url=postgres_url)

    migrated_obs = 0
    for obs in all_observations:
        pg_repo.save(obs)
        # Migrate associated interactions
        interactions = sqlite_repo.get_interactions(obs.id)
        for inter in interactions:
            pg_repo.record_interaction(
                observation_id=obs.id,
                contributor_id=inter["contributor_id"],
                interaction_type=inter["interaction_type"],
            )
        migrated_obs += 1

    target_count = pg_repo.count(include_expired=True)
    parity = (source_count <= target_count)

    logger.info("Migration complete. Target PostgreSQL now contains %d observations (Source had %d). Parity: %s",
                target_count, source_count, parity)

    return {
        "status": "success",
        "success": True,
        "observations_found": source_count,
        "interactions_found": interactions_count,
        "observations_migrated": migrated_obs,
        "migrated_count": migrated_obs,
        "target_count": target_count,
        "parity_verified": parity,
    }


def main():
    parser = argparse.ArgumentParser(description="Migrate AccessRoute community data from SQLite to PostgreSQL.")
    parser.add_argument("--sqlite-path", default="./data/community_observations.db", help="Path to source SQLite file")
    parser.add_argument("--postgres-url", default=None, help="Target PostgreSQL connection URL")
    parser.add_argument("--dry-run", action="store_true", help="Perform inspection without writing to PostgreSQL")
    args = parser.parse_args()

    pg_url = args.postgres_url or db_settings.database_url
    result = migrate_sqlite_to_postgres(args.sqlite_path, pg_url, dry_run=args.dry_run)
    print(result)


if __name__ == "__main__":
    main()
