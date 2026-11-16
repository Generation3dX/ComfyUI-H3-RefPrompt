from typing_extensions import override

from comfy_api.latest import ComfyExtension, io

from .nodes import H3AudioReference, H3ImageReference, H3Ref2VAPrompt, H3VideoReference

WEB_DIRECTORY = "./web"


class H3RefPromptExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [H3ImageReference, H3VideoReference, H3AudioReference, H3Ref2VAPrompt]


async def comfy_entrypoint() -> H3RefPromptExtension:
    return H3RefPromptExtension()
