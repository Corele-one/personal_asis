# Isolate the model provider

Business workflows will depend on a small model-provider boundary that returns structured, evidence-aware results, not on a particular cloud model SDK or prompt format. The first provider can be the user's preferred cloud service, while later provider, cost, and privacy changes do not require rewriting task, indexing, or rule behavior.
