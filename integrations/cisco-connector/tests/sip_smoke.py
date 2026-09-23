"""Container integration check: real loopback SIP/RTP with a generated tone, no Cisco needed."""
import argparse
import array
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave


def peer(folder):
    import pjsua2 as pj
    class Call(pj.Call):
        player = None
        def onCallMediaState(self, _):
            info = self.getInfo()
            for index, media in enumerate(info.media):
                if media.type == pj.PJMEDIA_TYPE_AUDIO and media.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                    self.player = pj.AudioMediaPlayer()
                    self.player.createPlayer(str(folder / "tone.wav"))
                    self.player.startTransmit(self.getAudioMedia(index))
    class Account(pj.Account):
        calls = []
        def onIncomingCall(self, prm):
            call = Call(self, prm.callId)
            self.calls.append(call)
            answer = pj.CallOpParam()
            answer.statusCode = 200
            call.answer(answer)
    ep = pj.Endpoint()
    ep.libCreate()
    cfg = pj.EpConfig()
    cfg.uaConfig.threadCnt = 0
    cfg.uaConfig.mainThreadOnly = True
    cfg.logConfig.level = cfg.logConfig.consoleLevel = 5
    ep.libInit(cfg)
    transport = pj.TransportConfig()
    transport.port = 5070
    transport.boundAddress = "127.0.0.1"
    transport.publicAddress = "127.0.0.1"
    ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, transport)
    ep.libStart()
    ep.audDevManager().setNullDev()
    ac = pj.AccountConfig()
    ac.idUri = "sip:fixture@127.0.0.1"
    ac.mediaConfig.transportConfig.port = 42000
    ac.mediaConfig.transportConfig.boundAddress = "127.0.0.1"
    ac.mediaConfig.transportConfig.publicAddress = "127.0.0.1"
    account = Account()
    account.create(ac)
    (folder / "ready").touch()
    while True:
        ep.libHandleEvents(100)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--peer")
    args = parser.parse_args()
    if args.peer:
        peer(Path(args.peer))
        return
    with tempfile.TemporaryDirectory(prefix="sip-test-") as directory:
        folder = Path(directory)
        with wave.open(str(folder / "tone.wav"), "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            samples = array.array("h", (int(10000 * math.sin(2 * math.pi * 440 * n / 16000)) for n in range(32000)))
            wav.writeframes(samples.tobytes())
        peer_log = (folder / "peer.log").open("w")
        server = subprocess.Popen([sys.executable, __file__, "--peer", directory], stdout=peer_log)
        try:
            deadline = time.monotonic() + 20
            while not (folder / "ready").exists():
                if server.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Loopback peer did not start")
                time.sleep(0.1)
            env = dict(os.environ, SIP_ID_URI="sip:assistant@127.0.0.1", SIP_PORT="5068", SIP_RTP_PORT="41000",
                       SIP_TRANSPORT="udp", SIP_SRTP="0", SIP_REGISTRAR="", SIP_PROXY="", SIP_PUBLIC_ADDRESS="127.0.0.1")
            result = subprocess.run([sys.executable, "-m", "meeting_gateway.sip_record", "--uri", "sip:fixture@127.0.0.1:5070",
                "--output", str(folder / "recording.wav"), "--seconds", "3"], env=env, timeout=20, capture_output=True)
            if result.returncode:
                manifest = folder / "recording.json"
                detail = manifest.read_text() if manifest.exists() else "No manifest"
                if (folder / "recording.wav").exists():
                    with wave.open(str(folder / "recording.wav"), "rb") as wav:
                        audio = array.array("h", wav.readframes(wav.getnframes()))
                        detail += f" samples={len(audio)} peak={max(map(abs, audio), default=0)}"
                print((folder / "peer.log").read_text()[-14000:])
                raise RuntimeError("Recorder failed: " + detail + result.stderr.decode(errors="replace")[-1500:])
            assert json.loads((folder / "recording.json").read_text())["success"] is True
            with wave.open(str(folder / "recording.wav"), "rb") as wav:
                frames = wav.readframes(wav.getnframes())
                audio = array.array("h", frames)
                assert len(audio) > 8000 and max(abs(sample) for sample in audio) > 1000
            print("PASS: outgoing SIP call, incoming RTP, non-silent WAV, clean finalization")
        finally:
            server.terminate()
            server.wait(timeout=10)
            peer_log.close()


if __name__ == "__main__":
    main()
