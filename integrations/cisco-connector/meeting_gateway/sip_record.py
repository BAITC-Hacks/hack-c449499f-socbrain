"""One outgoing SIP meeting per process, using the upstream PJSUA2 binding."""
import argparse
import gc
import json
import os
from pathlib import Path
import signal
import time
import wave


def main():
    import pjsua2 as pj

    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seconds", type=int, required=True)
    args = parser.parse_args()
    output = Path(args.output)
    outcome = output.with_suffix(".json")
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    class Account(pj.Account):
        def onIncomingCall(self, prm):
            incoming = pj.Call(self, prm.callId)
            reject = pj.CallOpParam()
            reject.statusCode = 486
            incoming.answer(reject)

    class Call(pj.Call):
        def __init__(self, account):
            super().__init__(account)
            self.done = False
            self.connected = False
            self.media_received = False
            self.failed = False
            self.recorder = None
            self.last_status = None

        def onCallState(self, _):
            info = self.getInfo()
            self.last_status = info.lastStatusCode
            if info.state == pj.PJSIP_INV_STATE_CONFIRMED:
                self.connected = True
            if info.state == pj.PJSIP_INV_STATE_DISCONNECTED:
                self.done = True

        def onCallMediaState(self, _):
            try:
                info = self.getInfo()
                for index, media in enumerate(info.media):
                    if media.type == pj.PJMEDIA_TYPE_AUDIO and media.status == pj.PJSUA_CALL_MEDIA_ACTIVE:
                        if self.recorder is None:
                            self.recorder = pj.AudioMediaRecorder()
                            self.recorder.createRecorder(str(output))
                        self.getAudioMedia(index).startTransmit(self.recorder)
            except pj.Error:
                self.failed = True

        def count_received(self):
            try:
                info = self.getInfo()  # Keep the SWIG owner alive while reading its media vector.
                for index, media in enumerate(info.media):
                    if media.type == pj.PJMEDIA_TYPE_AUDIO:
                        stats = self.getStreamStat(index)
                        if stats.rtcp.rxStat.pkt > 0:
                            self.media_received = True
            except pj.Error:
                pass

    endpoint = pj.Endpoint()
    endpoint.libCreate()
    account = call = None
    success = False
    error_type = None
    stage = "initialize"
    call_result = {}
    try:
        cfg = pj.EpConfig()
        cfg.uaConfig.threadCnt = 0
        cfg.uaConfig.mainThreadOnly = True
        cfg.logConfig.level = 0
        cfg.logConfig.consoleLevel = 0
        cfg.medConfig.clockRate = 16000
        endpoint.libInit(cfg)
        transport = os.getenv("SIP_TRANSPORT", "udp").lower()
        types = {"udp": pj.PJSIP_TRANSPORT_UDP, "tcp": pj.PJSIP_TRANSPORT_TCP, "tls": pj.PJSIP_TRANSPORT_TLS}
        tc = pj.TransportConfig()
        tc.port = int(os.getenv("SIP_PORT", "5060"))
        tc.boundAddress = os.getenv("SIP_BIND_ADDRESS", "0.0.0.0")
        tc.publicAddress = os.getenv("SIP_PUBLIC_ADDRESS", "")
        if transport == "tls":
            tc.tlsConfig.verifyServer = True
            tc.tlsConfig.CaListFile = os.getenv("SIP_CA_FILE", "/etc/ssl/certs/ca-certificates.crt")
        endpoint.transportCreate(types[transport], tc)
        endpoint.libStart()
        stage = "account"
        endpoint.audDevManager().setNullDev()
        ac = pj.AccountConfig()
        ac.idUri = '"[REC] Protocol AI assistant" <' + os.environ["SIP_ID_URI"] + '>'
        ac.regConfig.registrarUri = os.getenv("SIP_REGISTRAR", "")
        ac.sipConfig.authCreds.append(pj.AuthCredInfo("digest", os.getenv("SIP_REALM", "*"),
                                     os.getenv("SIP_USERNAME", ""), 0, os.getenv("SIP_PASSWORD", "")))
        proxy = os.getenv("SIP_PROXY", "")
        if proxy:
            ac.sipConfig.proxies.append(proxy)
        ac.mediaConfig.transportConfig.port = int(os.getenv("SIP_RTP_PORT", "40000"))
        ac.mediaConfig.transportConfig.portRange = 20
        ac.mediaConfig.transportConfig.publicAddress = os.getenv("SIP_PUBLIC_ADDRESS", "")
        ac.mediaConfig.srtpUse = int(os.getenv("SIP_SRTP", "1"))
        ac.mediaConfig.srtpSecureSignaling = 1 if transport == "tls" else 0
        account = Account()
        account.create(ac)
        stage = "registration"
        # Registration is optional for direct CMS/SBC routing.
        deadline = time.monotonic() + 30
        while ac.regConfig.registrarUri and not account.getInfo().regIsActive:
            if stopping or time.monotonic() >= deadline:
                raise RuntimeError("SIP registration did not complete")
            endpoint.libHandleEvents(100)
        call = Call(account)
        stage = "call"
        options = pj.CallOpParam(True)
        options.opt.audioCount = 1
        options.opt.videoCount = 0
        call.makeCall(args.uri, options)
        deadline = time.monotonic() + args.seconds
        answer_deadline = time.monotonic() + 60
        while not stopping and not call.done and not call.failed and time.monotonic() < deadline:
            endpoint.libHandleEvents(100)
            call.count_received()
            if not call.connected and time.monotonic() > answer_deadline:
                break
        call.count_received()
        success = call.connected and call.media_received and not call.failed
        if not call.done:
            call.hangup(pj.CallOpParam())
            end = time.monotonic() + 3
            while not call.done and time.monotonic() < end:
                endpoint.libHandleEvents(100)
    except Exception as exc:
        # SIP errors can contain credentials or private addressing; do not print them.
        success = False
        error_type = type(exc).__name__
    finally:
        if call is not None:
            call_result = {"connected": call.connected, "received_rtp": call.media_received,
                           "media_failed": call.failed, "sip_status": call.last_status}
            call.recorder = None
        call = None
        gc.collect()
        if account is not None:
            account.shutdown()
        account = None
        gc.collect()
        endpoint.libDestroy()
    try:
        with wave.open(str(output), "rb") as wav:
            success = success and wav.getnframes() > 0
    except (OSError, wave.Error):
        success = False
    temp = outcome.with_suffix(".tmp")
    temp.write_text(json.dumps({"success": success, "error_type": error_type, "stage": stage, **call_result}), encoding="utf-8")
    temp.replace(outcome)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
