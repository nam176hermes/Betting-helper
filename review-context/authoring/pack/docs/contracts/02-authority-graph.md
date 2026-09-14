# Authority graph boundary

The governed `docs/graphs/executable-discovery-graph.v1.json` declares the
`EXECUTABLE_DISCOVERY_GRAPH`, with terminal `DISCOVERY_COMPLETE`. Its eight nodes
and eight edges describe discovery only.

The governed `docs/graphs/non-authoritative-future-roadmap.v1.json` declares the
`NON_AUTHORITATIVE_FUTURE_ROADMAP`. Its twenty nodes are informational future work.
Both the roadmap and every roadmap node have `authority: NONE`, `executable: false`,
`may_start: false`, and `auto_activate: false`.

The two node sets are disjoint. Every edge has both endpoints in its own graph;
there is no cross-graph edge. Completing discovery does not activate roadmap work
or grant production authority. The existing
`authoring-tools/validate_authority_graph.py::validate_graph_partition` checks the
governed graph separation and future-authority flags; this Markdown records those
facts and does not grant additional authority.

AUTHORIZED_PRODUCTION_PHASES: NONE
