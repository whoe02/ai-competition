"""Sub-agents: the modules that have a model of their own.

A module that reaches a conclusion deterministically is a tool. A module that
asks a model for one is an agent, and it reaches the Butler through exactly the
same registry entry -- `kind="workflow"`, with `ToolSpec.agent` naming its
entry point. The Butler's reasoning loop never learns which is which.
"""
