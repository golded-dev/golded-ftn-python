# Security

Treat message archives as untrusted input. Concrete readers must validate
record boundaries, offsets and decoding. This core does not execute message
content or fetch addresses; it does not guarantee lossless archive handling.

Report vulnerabilities privately through [GitHub security advisories](https://github.com/golded-dev/golded-ftn-python/security/advisories/new).
Do not put private archives, message contents or credentials in public issues.
The supported version is 1.1.x.
