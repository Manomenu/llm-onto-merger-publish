import argparse
from agent_framework import Agent, AgentExecutor, WorkflowBuilder
from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential
from llm_onto_merger import settings


async def _main():
    parser = argparse.ArgumentParser(description="Ontology Merging System")
    parser.add_argument('--base', required=True, help='Path to base ontology')
    parser.add_argument('--candidate', required=True, help='Path to candidate ontology')
    parser.add_argument('--mappings', required=True, help='Path to OAEI-standard mappings')
    parser.add_argument('--output', default='merged_ontology.owl', help='Output file path')
    args = parser.parse_args()

    with open(args.base) as f:
        base = f.read()
    with open(args.candidate) as f:
        candidate = f.read()
    with open(args.mappings) as f:
        mappings = f.read()

    input_data = f"Base Ontology:\n{base}\n\nCandidate Ontology:\n{candidate}\n\nMappings:\n{mappings}"

    client = FoundryChatClient(
        project_endpoint=settings.foundry_project_endpoint,
        model=settings.model_deployment_name,
        credential=DefaultAzureCredential(),
    )

    executor_agent = Agent(
        client=client,
        instructions=("You are an ontology processing executor. Load and prepare the provided base ontology, candidate ontology, and mappings for merging. Output the prepared data in a structured format."),
        name="executor",
    )

    merge_agent = Agent(
        client=client,
        instructions=("You are an ontology merging expert. Given the base ontology, candidate ontology, and mappings, produce the merged ontology in OWL format. Ensure the merge is consistent and resolves conflicts using the mappings."),
        name="merger",
    )

    executor_executor = AgentExecutor(executor_agent, context_mode="last_agent")
    merge_executor = AgentExecutor(merge_agent, context_mode="last_agent")

    workflow_agent = WorkflowBuilder(
            start_executor=executor_executor,
            output_executors=[merge_executor],
        ).add_edge(executor_executor, merge_executor).build() .as_agent()

    async with workflow_agent as agent:
        response = await agent.run(input_data)
        with open(args.output, 'w') as f:
            f.write(response.text)
        print(f"Merged ontology saved to {args.output}")


def main():
    import asyncio
    asyncio.run(_main())


if __name__ == "__main__":
    main()
