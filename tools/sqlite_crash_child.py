"""Registered SQLite entrypoint shares the actual offline ingest crash child."""

from tools.loopback_ack_crash_child import main as ingest_crash_main


def contract_not_implemented() -> None:
    raise RuntimeError("E_CONTRACT_NOT_IMPLEMENTED:V636-P01-T04")


def main() -> None:
    ingest_crash_main()


if __name__ == "__main__":
    main()
