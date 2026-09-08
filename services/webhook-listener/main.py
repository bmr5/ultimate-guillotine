"""Launch the BlueBubbles webhook listener. Supervised by launchd on the Mac mini.

The launcher body lives in `ultimate_guillotine.listener.run` so it can be shared
with `ug listener run`.
"""
from ultimate_guillotine.listener.run import main

if __name__ == "__main__":
    main()
