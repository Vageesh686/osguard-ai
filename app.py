"""Local Streamlit entry point for OSGuard AI."""

from osguard.frontend import (
    _get_supervisor_graph,
    _render_approval_controls,
    _render_supervisor_result,
    _store_graph_result,
    main,
)

main()
