"""v0.2 evo loop for aura-harness (#4946).

The multi-objective search lives in Aura (aura/evo_server.aura) on std/moead,
std/pareto, std/proposer, std/surrogate and the evo:record! worldline. This
package is the host side: it decodes a genome into the harness decision table,
runs the simulated solver, and reports the objective vector. Nothing here
calls a model or the network.
"""