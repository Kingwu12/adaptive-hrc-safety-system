# Optional OptiTrack NatNet SDK client

The current dashboard uses the dependency-free `NatNetV4Listener` in [optitrack_transport.py](../src/hrc_safety/mocap/optitrack_transport.py). It does not require a vendor Python client.

The older `live_run.py` path can use `OptiTrackListener`, which loads an externally supplied `NatNetClient.py`. Obtain the matching Python sample and its companion modules from the official OptiTrack NatNet SDK. Place the required files here or provide the supported `--natnet-client` path to the older runner. Keep the SDK version and redistribution terms with any vendor files.

These are separate receiver implementations; adding an SDK client does not change the dashboard's parser or give it protocol negotiation. See the [integration tutorial](../docs/helmet-xsens-integration.md) for its supported data path.
