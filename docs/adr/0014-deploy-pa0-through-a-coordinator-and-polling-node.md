# Deploy PA0 through a coordinator and polling local node

PA0 will deploy a VPS coordinator, Mac and ROG local nodes that initiate outbound polling, and a minimal private PWA. The ROG node runs as a WSL user service. The PWA submits searches to the coordinator; each available local node executes local retrieval and returns evidence results, while work for sleeping nodes waits, preserving phone access without exposing either device service to the public internet.
