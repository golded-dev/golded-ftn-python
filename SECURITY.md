# Security

Treat message archives as untrusted input. Concrete readers must impose their
own size limits and validate format offsets. This core does not execute message
content or fetch addresses and does not guarantee lossless archive handling.

A public security-reporting channel has not been configured because the package
is not published. Before public release, maintainers must configure a private
reporting channel and document it here. Do not post sensitive archives or
credentials in a public issue. The initial supported version is 1.0.0.
