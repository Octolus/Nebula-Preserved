        private void BeginResourceSelection(Peer peer, string kind, string item)
        {
            try
            {
                Bound(peer);
                if (peer.resourcePending != null) throw new Rejected("resource_selection_pending");
                RequireResource(item, kind == "companions" ? peer.account.companion_ids : peer.account.locomotion_ids);
                long revision = kind == "companions" ? peer.companionRevision : peer.locomotionRevision;
                peer.resourcePending = resourceSelections.Begin(peer.account.guid, kind, item, revision, Now());
            }
            catch (Exception)
            {
                RestoreResourceSelection(peer, kind);
                throw;
            }
        }

        private void RestoreResourceSelection(Peer peer, string kind)
        {
            // Original 15/17 receivers only apply local visuals; they do not
            // invoke the wheel OnClick sender. Never manufacture a new request.
            try
            {
                Bound(peer);
                string item = kind == "companions" ? peer.account.selected_companion : peer.account.selected_locomotion;
                RequireResource(item, kind == "companions" ? peer.account.companion_ids : peer.account.locomotion_ids);
                Send(peer, Join(kind == "companions" ? 17 : 15, peer.account.guid, item));
            }
            catch (Exception) { } // disconnected/stale identity receives nothing
        }

        private void PumpResourceSelections()
        {
            foreach (Peer peer in peers.Values.ToArray())
            {
                var request = peer.resourcePending;
                if (request == null)
                {
                    if (peer.account == null) continue;
                    try
                    {
                        Bound(peer);
                        if (peer.account.companion_revision > peer.companionRevision)
                        {
                            peer.companion = peer.account.selected_companion;
                            peer.companionRevision = peer.account.companion_revision;
                            Broadcast(Join(17, peer.account.guid, peer.companion), peer);
                            Send(peer, Join(17, peer.account.guid, peer.companion));
                        }
                        if (peer.account.locomotion_revision > peer.locomotionRevision)
                        {
                            peer.locomotion = peer.account.selected_locomotion;
                            peer.locomotionRevision = peer.account.locomotion_revision;
                            Broadcast(Join(15, peer.account.guid, peer.locomotion), peer);
                            Send(peer, Join(15, peer.account.guid, peer.locomotion));
                        }
                    }
                    catch (Exception) { }
                    continue;
                }
                try
                {
                    Bound(peer); // re-acquire current GUID, account and exact allocation
                    if (peer.account.guid != request.guid || request.instance_id != instanceId || request.instance_owner != statusOwner)
                        throw new Rejected("resource_selection_session_changed");
                    if (Now() >= request.expires_at) throw new Rejected("resource_selection_deadline");
                    var ack = resourceSelections.Poll(request);
                    if (ack == null)
                    {
                        if (Now() >= request.expires_at) throw new Rejected("resource_selection_deadline");
                        continue;
                    }
                    if (ack.status != "committed") throw new Rejected("resource_selection_not_committed");
                    long exportedRevision = request.kind == "companions" ? peer.account.companion_revision : peer.account.locomotion_revision;
                    string exportedItem = request.kind == "companions" ? peer.account.selected_companion : peer.account.selected_locomotion;
                    if (exportedRevision < ack.revision) continue; // durable ack may precede atomic account export
                    if (exportedRevision != ack.revision || exportedItem != request.item_id)
                        throw new Rejected("resource_selection_ack_superseded");
                    RequireResource(request.item_id, request.kind == "companions" ? peer.account.companion_ids : peer.account.locomotion_ids);
                    if (request.kind == "companions")
                    {
                        peer.companion = request.item_id;
                        peer.companionRevision = ack.revision;
                    }
                    else
                    {
                        peer.locomotion = request.item_id;
                        peer.locomotionRevision = ack.revision;
                    }
                    Broadcast(Join(request.kind == "companions" ? 17 : 15, request.guid, request.item_id), peer);
                    Send(peer, Join(request.kind == "companions" ? 17 : 15, request.guid, request.item_id));
                    resourceSelections.Finish(request);
                    peer.resourcePending = null;
                }
                catch (Exception)
                {
                    Record("rejected", peer.connection, -1, "resource_selection_failed_or_stale");
                    if (peer.account != null && peer.account.guid == request.guid)
                        RestoreResourceSelection(peer, request.kind);
                    try { resourceSelections.Finish(request); } catch (Exception) { }
                    peer.resourcePending = null;
                }
            }
        }
