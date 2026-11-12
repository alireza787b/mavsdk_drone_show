"""Exercise the embedded API loop and mission FD/session contract with real gRPC.

The bounded child isolates process-wide loop selection from the pytest process.
It uses no MAVLink server, aircraft transport or external network.
"""
import subprocess
import sys


def test_embedded_loop_can_spawn_repeated_controllers_with_active_grpc():
    program = r'''
import asyncio, os, sys, tempfile
import grpc
import uvicorn

# Match DroneAPIServer.run without starting an HTTP listener. Uvicorn 0.32's
# auto setup otherwise replaces the process-wide policy when uvloop is present.
config = uvicorn.Config("unused:app", loop="asyncio")
config.setup_event_loop()
assert type(asyncio.get_event_loop_policy()).__module__.startswith("asyncio")

async def exercise():
    channel = grpc.aio.insecure_channel("127.0.0.1:1")
    ready = asyncio.create_task(channel.channel_ready())
    await asyncio.sleep(0.05)
    try:
        for index in range(30):
            with tempfile.TemporaryFile() as evidence:
                evidence.write(b"owned-evidence")
                evidence.seek(0)
                child = await asyncio.create_subprocess_exec(
                    sys.executable, "-c",
                    "import os,sys; assert os.getsid(0)==os.getpid(); "
                    "assert os.read(int(sys.argv[1]),64)==b'owned-evidence'; print('ok')",
                    str(evidence.fileno()), pass_fds=(evidence.fileno(),),
                    start_new_session=True, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE)
                out, err = await asyncio.wait_for(child.communicate(), 3)
                assert child.returncode == 0, err
                assert out.strip() == b"ok"
    finally:
        ready.cancel()
        await asyncio.gather(ready, return_exceptions=True)
        await channel.close()

asyncio.run(exercise())
print("30 controller execs verified")
'''
    result = subprocess.run([sys.executable, "-c", program], capture_output=True,
                            text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert "30 controller execs verified" in result.stdout
