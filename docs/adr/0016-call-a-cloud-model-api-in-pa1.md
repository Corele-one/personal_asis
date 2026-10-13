# Call a cloud model API in PA1

PA1 will invoke a cloud model through the existing provider boundary rather than relying on manual copy-and-paste into ChatGPT. One selected online local node builds the context bundle and calls the provider directly; cross-node synthesis is deferred, so the VPS never aggregates source text. Every invocation remains constrained to an evidence-linked minimal context bundle.
