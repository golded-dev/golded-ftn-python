# Security

Treat message archives as untrusted input. Concrete readers must validate
record boundaries, offsets and decoding. This core does not execute message
content or fetch addresses; it does not guarantee lossless archive handling.

Report vulnerabilities privately through [GitHub security advisories](https://github.com/golded-dev/golded-ftn-python/security/advisories/new).
Do not put private archives, message contents or credentials in public issues.
The local development version is 1.2.0. No package-index release has been made.
Writer sessions are offline and reject concurrent GoldED access. Rollback covers
ordinary operation failures; it does not guarantee recovery after process death
or power loss. Private base files and credentials do not belong in reports.
