# Analyst graph arrangement (UX-1)

Blockchain Graph and Discovery Graph share one SVG interaction layer. Drag a node
with the primary pointer to move and pin it; PINNED and a dashed border mark pins.
Click a node, then use Pin selected node / Unpin selected node. A drag does not
activate the node's investigative actions. Drag empty space to pan.

Auto layout restores deterministic default positions for unpinned nodes only.
Reset layout clears saved positions/pins for the current graph and restores all
nodes to the default layout. Fit to graph includes manually moved nodes. Reset
view changes the viewport only; it does not reset analyst arrangement.

Positions live in browser sessionStorage, with an in-page fallback if storage is
unavailable. Refresh, workspace navigation and reopening the same graph in the
same tab retain positions. Closing the browser session clears them; they are not
shared across tabs/devices or written to SQLite. No credentials are stored.

Keys include graph type, chain, canonical focus wallet and (for Discovery) run ID.
Hops and Discovery pagination share the same context so returning nodes retain
positions. New nodes receive deterministic positions; existing nodes keep theirs.
The technical-cluster overlay changes badges only and leaves positions intact.
Manual arrangement can deliberately overlap nodes; unpin and Auto layout or Reset
layout restore the existing deterministic arrangement.

**Manual graph arrangement is analyst presentation state. Spatial proximity has
NO analytical meaning.** Moving nodes does not create transactions, relationships,
Attribution evidence, cluster membership, Labels, risk or common-control findings.

Multi-select/group dragging is deferred. Fund Flow has a separate selected-path
renderer; integrating it with this layer is a follow-up, not a duplicated drag
implementation. Attribution overlay entity cards are not movable in UX-1.
