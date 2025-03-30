# Trellis MCP Server

Trellis MCP provides an interface between AI assistants and [Trellis](https://github.com/microsoft/TRELLIS) via [Model Context Protocol (MCP)](https://modelcontextprotocol.io). 

### Disclaimer
This project shows a very **minimal** integration of MCP with [Trellis](https://github.com/microsoft/TRELLIS): a lightweight and opensource text-to-3d/image-to-3d 3DAIGC model. Compared with existing [rodin integration in blender-mcp](https://github.com/ahujasid/blender-mcp) and [tripo integration](https://github.com/VAST-AI-Research/tripo-mcp), it has following advantages: 
* **Faster and memory-efficient**: You can deploy the TRELLIS API on your own PC with only 8GPU+ VRAM, while can generate a textured mesh from text in only ~15s.
* **FREE**: You DON'T have to pay expensive API from Rodin/Meshy/Tripo.

**BUT IT HAS FOLLOWING LIMITATIONS:**
* Trellis is open-source and there is no off-the-shelf API model providers, you have to deploy it by yourself (refer to [README](https://github.com/FishWoWater/TRELLIS/blob/dev/README_api.md)).
* The API/Prompt has NOT been fully tested/tuned, may suffer from stability issues. 

So use it at your own risk. 


## Features

- [x] Generate 3D asset from natural language(**TEXT**) using Trellis API and import into blender
- [ ] Generate texture/materials from natural language(**TEXT**) for a given 3D mesh using Trellis API and import into blender

## Roadmap  

### Prerequisites
- Python 3.10+
- [Blender](https://www.blender.org/download/)
- [Trellis Blender Addon](https://github.com/FishWoWater/trellis_blender)
- [Trellis API Backend](https://github.com/FishWoWater/TRELLIS)
- Claude / Cursor / Windsurf

### Installation
#### 1. Trellis blender addon 
1. Download Trellis Blender Addon from [here](https://github.com/FishWoWater/trellis_blender)
2. Open Blender -> Edit -> Preferences -> Add-ons -> Install from file -> Select the downloaded addon -> Install
3. In 3D Viewport -> View3D > Sidebar > TRELLIS -> Start MCP Server 

#### 2. Configure API backend 
> As trellis is a free open-source text-to-3d model, you need to deploy your own trellis API backend with reference to [README](https://github.com/FishWoWater/TRELLIS/blob/dev/README_api.md)
``` shell 
# clone an API fork of trellis 
git clone https://github.com/FishWoWater/TRELLIS
cd TRELLIS

# EDIT BACKEND URL in trellis_api/config.py

# configure the # of text workers and start ai worker
python trellis_api/ai_worker.py --text-workers-per-gpu 1 --image-workers-per-gpu 0

# start web server 
python trellis_api/web_server.py 
```

#### 3. Configure the MCP server on Windsurf/Cursor/Claude 
``` shell 
# first install uv
# on mac os 
# brew install uv  
pip install uv 

# paste into windsurf mcp servers 
"""
{
    "mcpServers": {
        "blender": {
            "command": "uvx",
            "args": [
                "trellis-mcp"
            ]
        }
    }
}
"""

# for debugging 
git clone https://github.com/FishWoWater/trellis-mcp
uv run main.py 
```

## Acknowledgements
- Backbone and brain: [Trellis](https://github.com/microsoft/TRELLIS)
- Inspiration: [blender-mcp](https://github.com/ahujasid/blender-mcp)
- Borrow a lot of code [Tripo MCP Service](https://github.com/VAST-AI-Research/tripo-mcp)

