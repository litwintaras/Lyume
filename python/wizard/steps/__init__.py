"""Wizard steps registry."""

def all_steps():
    from wizard.steps.identity import IdentityStep
    from wizard.steps.backend import BackendStep
    from wizard.steps.embedding import EmbeddingStep
    from wizard.steps.docker import DockerStep
    from wizard.steps.database import DatabaseStep
    from wizard.steps.memory_import import MemoryImportStep
    from wizard.steps.summary import SummaryStep
    return [
        IdentityStep(),
        BackendStep(),
        EmbeddingStep(),
        DockerStep(),
        DatabaseStep(),
        MemoryImportStep(),
        SummaryStep(),
    ]
