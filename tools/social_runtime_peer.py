"""Opt-in localhost social/visitor fixture; default is a socket-free self-test.

Uses an explicitly named fixture account, never a native user's account.  It can
accept only an explicitly allowed sender, follow that sender's InviteToJoin6 via
the recovered HTTP lookup/load chain, and reply to one exact private message.
This is a protocol fixture, not a second native UI or a furniture editor.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import socket
import struct
import time

import core_runtime_peer as core


def token(value: str, label: str, limit: int = 128) -> str:
    if not value or len(value) > limit or any(c in value for c in "#\x00<>"):
        raise core.ProtocolStop("invalid_" + label)
    return value


def accept_packet(guid: str, source: str, notice_type: int, platform: int) -> str:
    if notice_type not in (0, 1, 5) or platform not in (0, 1):
        raise core.ProtocolStop("unsupported_notification_acceptance")
    return f"26#{token(guid,'guid')}#{token(source,'source')}#{notice_type}#{platform}"


def private_packet(guid: str, target: str, platform: int, message: str) -> str:
    if platform not in (0, 1):
        raise core.ProtocolStop("unsupported_target_platform")
    return f"13#{token(guid,'guid')}#{token(target,'target')}#{platform}#{token(message,'message',4096)}#1"


def allocate(http, guid: str, account: str, requested: str, desired_guid: str, timeout: float):
    response = http.call("N2LoadSpace", [guid, account, requested, "true", "", desired_guid])
    if response != guid + "#false#false":
        raise core.ProtocolStop("visitor_allocation_rejected")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        fields = http.call("N2SpaceLoading", [guid, account]).split("#")
        if fields == [guid, "false"]:
            time.sleep(0.25)
            continue
        if len(fields) != 6 or fields[:2] != [guid, "true"] or fields[3] != requested or fields[4] != core.HOST:
            raise core.ProtocolStop("visitor_allocation_outside_requested_local_scope")
        try:
            port = int(fields[5])
        except ValueError as exc:
            raise core.ProtocolStop("visitor_invalid_port") from exc
        if str(port) != fields[5] or not 1 <= port <= 65535:
            raise core.ProtocolStop("visitor_invalid_port")
        return core.Allocation(fields[2], fields[3], fields[4], port)
    raise core.ProtocolStop("visitor_allocation_timeout")


class SocialPeer(core.RuntimePeer):
    def __init__(self, sock, state, log, args, milestones):
        super().__init__(sock, state, log, "", "")
        self.args, self.milestones = args, milestones
        self.invite = None

    def handle_application(self, ciphertext):
        if not ciphertext:
            raise core.ProtocolStop("null_ciphertext")
        fields = core.decrypt(ciphertext).split("#")
        if fields[0] == "19":
            if len(fields) != 6:
                raise core.ProtocolStop("notification_response_contract_mismatch")
            name, platform, notice_type, arguments, ticks = fields[1:]
            if name != self.args.allow_source or platform != str(self.args.source_platform):
                self.log.write("notification_ignored", source_sha256=core.digest_text(name))
                return
            try:
                notice_type, parsed_ticks = int(notice_type), int(ticks)
            except ValueError as exc:
                raise core.ProtocolStop("notification_numeric_contract_mismatch") from exc
            if parsed_ticks < 0 or arguments:
                raise core.ProtocolStop("unsupported_notification_arguments")
            if notice_type in (0, 1, 5):
                self.send_nebula(accept_packet(self.state.guid, name, notice_type, int(platform)), "notification_accept_26")
                if notice_type in (0, 1):
                    self.milestones["private_consent_sent" if notice_type == 0 else "friend_acceptance_sent"] = True
                self.log.write("notification_accepted", notification_type=notice_type)
            elif notice_type == 6 and self.args.follow_invites:
                self.invite = (name, int(platform))
                self.log.write("invite6_received", source_sha256=core.digest_text(name))
            else:
                self.log.write("notification_unsupported", notification_type=notice_type)
            return
        if fields[0] == "13" and len(fields) == 6 and fields[5] == "1":
            if fields[2] != self.args.allow_source or fields[3] != str(self.args.source_platform):
                self.log.write("private_chat_ignored", group_sha256=core.digest_text(fields[2]))
                return
            own = fields[1] == self.state.guid
            self.log.write("private_chat_receive", own_echo=own, sender_guid_sha256=core.digest_text(fields[1]),
                           message_sha256=core.digest_text(fields[4]))
            if not own and fields[4] == self.args.expect_message:
                self.milestones["private_message_received"] = True
                if not self.milestones.get("private_reply_sent"):
                    self.send_nebula(private_packet(self.state.guid, self.args.allow_source, self.args.source_platform,
                                                   self.args.reply_message), "private_chat_reply")
                    self.milestones["private_reply_sent"] = True
            return
        if fields[0] == "13":
            # Public chat is outside this fixture's response policy. In
            # particular do not trigger the base public-chat auto-responder.
            self.log.write("other_chat_ignored")
            return
        super().handle_application(ciphertext)


def offline_self_test():
    # Capture actual fixture sends without a socket or server.
    class Capture:
        def __init__(self): self.frames = []
        def sendall(self, frame): self.frames.append(frame)
    guid = "a" * 32
    args = argparse.Namespace(allow_source="Actual Native", source_platform=1, follow_invites=True,
                              expect_message="Private native check.", reply_message="Private peer reply.")
    capture, state, milestones = Capture(), core.PeerState(guid), {}
    peer = SocialPeer(capture, state, core.JsonLog(io.BytesIO()), args, milestones)
    peer.handle_application(core.encrypt("19#Actual Native#1#1##638000000000000000"))
    reader = core.Reader(capture.frames[0][4:]); reader.f64(); reader.u16()
    assert core.decrypt(reader.mirror_string()) == f"26#{guid}#Actual Native#1#1#StandaloneWindows"
    assert milestones["friend_acceptance_sent"]
    peer.handle_application(core.encrypt("19#Someone Else#1#1##638000000000000000"))
    assert len(capture.frames) == 1
    peer.handle_application(core.encrypt("19#Actual Native#1#6##638000000000000000"))
    assert peer.invite == ("Actual Native", 1) and len(capture.frames) == 1  # no invented26 for invite6
    peer.handle_application(core.encrypt("13#" + "b"*32 + "#Actual Native#1#Private native check.#1"))
    assert milestones["private_message_received"] and milestones["private_reply_sent"]
    assert len(capture.frames) == 2
    peer.handle_application(core.encrypt("13#" + "b"*32 + "#Public#-1#Public text.#0"))
    assert len(capture.frames) == 2
    try: accept_packet(guid, "Actual Native", 6, 1)
    except core.ProtocolStop: pass
    else: raise AssertionError("invite6 must not emit26")
    try: private_packet(guid,"Injected#Name",1,"hello")
    except core.ProtocolStop: pass
    else: raise AssertionError("framing injection")
    return 8


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", action="store_true")
    p.add_argument("--http-port", type=int, default=8080)
    p.add_argument("--account-id", default="preservation-social-visitor")
    p.add_argument("--username", default="Preservation Social Visitor")
    p.add_argument("--allow-source", default="Native test account")
    p.add_argument("--source-platform", type=int, choices=(0,1), default=1)
    p.add_argument("--follow-invites", action="store_true")
    p.add_argument("--duration", type=float, default=180)
    p.add_argument("--expect-message", default="Private native check.")
    p.add_argument("--reply-message", default="Private peer reply.")
    p.add_argument("--log", type=Path)
    a = p.parse_args(argv)
    if not 1 <= a.http_port <= 65535 or not 1 <= a.duration <= 600:
        p.error("port must be1..65535 and duration1..600")
    for value, label in ((a.account_id,"account"),(a.username,"username"),(a.allow_source,"source")):
        token(value,label)
    token(a.expect_message,"message",4096); token(a.reply_message,"message",4096)
    if a.account_id == core.ACCOUNT_ID or not a.account_id.startswith("preservation-social-"):
        p.error("use a distinct preservation-social-* fixture account")
    if a.run and a.log is None: p.error("--log is required for --run")
    return a


def run(args):
    core.ACCOUNT_ID, core.USERNAME = args.account_id, args.username  # only this isolated fixture process
    personal = json.loads((core.ROOT/"protocol/http-nonminigame-gap-audit.json").read_text())["personal_space_navigator_names"]
    allowed = set(personal) - {"CampSilverLake","CutteridgeEstate","SorcerersEyrie"}
    args.log.parent.mkdir(parents=True,exist_ok=True)
    sock = None
    with args.log.open("xb") as stream:
        log = core.JsonLog(stream); milestones = {}
        log.write("social_fixture_start", account=args.account_id, http_port=args.http_port, real_native_client=False)
        try:
            http = core.HttpWire(args.http_port,log,30)
            guid, allocation = core.bootstrap(http,30)
            deadline = time.monotonic()+args.duration
            while time.monotonic() < deadline:
                sock = socket.create_connection((core.HOST,allocation.port),timeout=5); sock.settimeout(0.25)
                peer = SocialPeer(sock,core.PeerState(guid),log,args,milestones)
                peer.send_ready_add_player(); next_ping = time.monotonic()+5
                log.write("social_fixture_connection", instance_id=allocation.instance_id,scene=allocation.scene,port=allocation.port)
                while time.monotonic() < deadline:
                    if time.monotonic() >= next_ping:
                        peer.send([core.packed_message("Mirror.NetworkPingMessage",struct.pack("<d",time.monotonic()))],"network_ping")
                        next_ping = time.monotonic()+5
                    try: peer.handle_batch(core.receive_frame(sock))
                    except socket.timeout: continue
                    if peer.state.announced:
                        milestones["announced"] = True
                        if allocation.scene in allowed: milestones["personal_space_announced"] = True
                    if peer.invite:
                        name, platform = peer.invite
                        lookup = http.call("N2GetPsidglobalAndGuidByUsernamePlatform",[guid,name,str(platform)]).split("#")
                        if len(lookup) != 3 or lookup[1] not in allowed or len(lookup[2]) != 32:
                            raise core.ProtocolStop("invite_lookup_outside_reviewed_personal_scope")
                        sock.close(); sock = None
                        allocation = allocate(http,guid,args.account_id,lookup[1],lookup[2],30)
                        milestones["invite_lookup_and_allocation"] = True
                        break
                else: break
                if not peer.invite: break
            log.write("social_fixture_complete",milestones=milestones,full_social_parity=False)
            return 0 if milestones.get("announced") else 3
        except (OSError,EOFError,core.ProtocolStop) as exc:
            log.write("social_fixture_stopped",reason=type(exc).__name__,detail=str(exc));return 4
        finally:
            if sock is not None: sock.close()


def main(argv=None):
    args = parse_args(argv); checks = offline_self_test()
    if not args.run:
        print(json.dumps({"offline_checks":checks,"listeners_started":False,"connections_performed":False,
                          "purpose":"explicit-source notification/private-chat and invite6 visitor fixture"}))
        return 0
    return run(args)


if __name__ == "__main__": raise SystemExit(main())

