using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.Text;

namespace NebulaPreservation
{
    // Pure replacement policy, not recovered original server source.
    // Wire/DTO constraints: protocol/minigame-contracts.json; source binary
    // SHA256 c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac.
    // No Unity, Mirror, filesystem, clock, RNG, sockets or background work.
    public sealed class NebulaMinigameState
    {
        public sealed class Identity
        {
            public readonly string Guid;
            public readonly string DisplayName;
            public readonly string PlatformId;

            public Identity(string guid, string displayName, string platformId)
            {
                Guid = guid;
                DisplayName = displayName;
                PlatformId = platformId;
            }
        }

        public sealed class Delivery
        {
            public readonly string TargetGuid;
            public readonly string ExceptGuid;
            public readonly string Payload;

            private Delivery(string targetGuid, string exceptGuid, string payload)
            {
                TargetGuid = targetGuid;
                ExceptGuid = exceptGuid;
                Payload = payload;
            }

            internal static Delivery To(string guid, string payload) => new Delivery(guid, null, payload);
            internal static Delivery Others(string exceptGuid, string payload) => new Delivery(null, exceptGuid, payload);
        }

        public sealed class Rejected : Exception
        {
            public readonly string Code;
            public Rejected(string code) : base(code) { Code = code; }
        }

        private sealed class BoardTable
        {
            public readonly Identity[] Seats = new Identity[2];
            public readonly char[] Cells = new char[9];
            public int Rules;
            public int Turn;
            public bool Playing;
            public BoardTable() { ClearBoard(); }
            public void ClearBoard()
            {
                for (int i = 0; i < Cells.Length; ++i) Cells[i] = '0';
                Turn = 0;
                Playing = false;
            }
        }

        private sealed class DartsTable
        {
            public readonly Identity[] Seats = new Identity[2];
            public int Rules;
            public int RequestedPlayers = 1;
            // Darts is a lobby-only reconstruction. Keeping isActive false
            // prevents a query snapshot from pretending a scored game exists.
        }

        private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
        private static readonly string[] BoardRules = { "None", "TicTacToe", "Chess", "Draughts" };
        private static readonly string[] DartsRules = { "Game301", "Game501", "Game701", "Cricket", "AroundTheClock" };
        private readonly BoardTable[] boards;
        private readonly DartsTable[] darts;
        private readonly Func<string, Identity> resolveIdentity;

        public bool ReadyForOriginalServerParity => false;
        public int BoardTableCount => boards.Length;
        public int DartsTableCount => darts.Length;

        // Counts must describe the loaded scene. The complete Nexus inventory
        // confirms 0/0; other scans retain unresolved component limits. The
        // Bowling Darts manager configures3 but has activeSelf=false. Minigame
        // gameplay is deferred; positive counts require explicit scene proof.
        public NebulaMinigameState(int boardTableCount, int dartsTableCount,
            Func<string, Identity> resolveIdentity)
        {
            if (boardTableCount < 0 || boardTableCount > 64 || dartsTableCount < 0 || dartsTableCount > 64)
                throw new ArgumentOutOfRangeException("table counts must be between 0 and 64");
            this.resolveIdentity = resolveIdentity ?? throw new ArgumentNullException(nameof(resolveIdentity));
            boards = new BoardTable[boardTableCount];
            darts = new DartsTable[dartsTableCount];
            for (int i = 0; i < boards.Length; ++i) boards[i] = new BoardTable();
            for (int i = 0; i < darts.Length; ++i) darts[i] = new DartsTable();
        }

        public bool Handles(int opcode) => (opcode >= 32 && opcode <= 37) ||
            opcode == 80 || opcode == 81 || opcode == 82 || opcode == 84 || opcode == 85 || opcode == 86;

        // args exclude both opcode and the generic C2S platform-name trailer.
        // The host must bind callerGuid to the authenticated connection first.
        // Do not broadcast deliveries to peers still assembling their scene.
        public IReadOnlyList<Delivery> Handle(string callerGuid, int opcode, string[] args)
        {
            if (!Handles(opcode)) throw new Rejected("minigame_opcode_not_supported");
            if (args == null || args.Length == 0 || String.IsNullOrEmpty(callerGuid) || args[0] != callerGuid)
                throw new Rejected("minigame_session_not_owned");
            Identity caller = IdentityFor(callerGuid);
            var output = new List<Delivery>();
            switch (opcode)
            {
                case 32: BoardJoin(caller, args, output); break;
                case 33: BoardSelect(caller, args, output); break;
                case 34: BoardStart(caller, args, output); break;
                case 35: BoardMove(caller, args, output); break;
                case 36:
                    Count(args, 2);
                    int bi = TableIndex(args[1], boards.Length);
                    RequireSeat(boards[bi].Seats, caller.Guid);
                    RemoveBoard(caller.Guid, bi, true, output);
                    break;
                case 37:
                    Count(args, 1);
                    output.Add(Delivery.To(caller.Guid, BoardSnapshot()));
                    break;
                case 80: DartsJoin(caller, args, output); break;
                case 81:
                    Count(args, 2);
                    int di = TableIndex(args[1], darts.Length);
                    RequireSeat(darts[di].Seats, caller.Guid);
                    RemoveDarts(caller.Guid, di, true, output);
                    break;
                case 82: DartsSelect(caller, args, output); break;
                case 84:
                    Count(args, 2);
                    RequireSeat(darts[TableIndex(args[1], darts.Length)].Seats, caller.Guid);
                    throw new Rejected("darts_start_requires_unrecovered_score_and_turn_authority");
                case 85:
                    Count(args, 3);
                    RequireSeat(darts[TableIndex(args[1], darts.Length)].Seats, caller.Guid);
                    string[] shot = DecodeTokens(args[2], 5);
                    foreach (string number in shot) FiniteFloat(number);
                    throw new Rejected("darts_shot_requires_unrecovered_scene_hit_adjudication");
                case 86:
                    Count(args, 1);
                    output.Add(Delivery.To(caller.Guid, DartsSnapshot(caller.Guid)));
                    break;
            }
            return Freeze(output);
        }

        public IReadOnlyList<Delivery> Disconnect(string guid)
        {
            var output = new List<Delivery>();
            if (String.IsNullOrEmpty(guid)) return Freeze(output);
            for (int i = 0; i < boards.Length; ++i)
                if (Seat(boards[i].Seats, guid) >= 0) RemoveBoard(guid, i, false, output);
            for (int i = 0; i < darts.Length; ++i)
                if (Seat(darts[i].Seats, guid) >= 0) RemoveDarts(guid, i, false, output);
            return Freeze(output);
        }

        private void BoardJoin(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 3);
            if (args[1] != caller.PlatformId) throw new Rejected("board_platform_id_not_owned");
            int index = TableIndex(args[2], boards.Length);
            BoardTable table = boards[index];
            if (Seat(table.Seats, caller.Guid) >= 0) throw new Rejected("minigame_already_seated");
            RequireNotSeated(caller.Guid);
            int occupied = Occupied(table.Seats);
            if (table.Playing || occupied == 2)
            {
                output.Add(Delivery.To(caller.Guid, Wire(32, Int(index), table.Playing ? "4" : "1", BoardData(table))));
                return;
            }
            table.Seats[occupied] = caller;
            // Reply state describes pre-join availability: Free for seat0,
            // Awaiting for seat1. It is not an echo of the request's PS4ID.
            output.Add(Delivery.To(caller.Guid, Wire(32, Int(index), occupied == 0 ? "0" : "2", BoardData(table))));
            output.Add(Delivery.Others(caller.Guid, Wire(39, Int(index), "", BoardData(table))));
        }

        private void BoardSelect(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 3);
            int index = TableIndex(args[1], boards.Length);
            BoardTable table = boards[index];
            RequireOwner(table.Seats, caller.Guid);
            if (table.Playing) throw new Rejected("board_match_already_playing");
            int rules = Integer(args[2]);
            // New, explicit replacement policy: only standard TicTacToe has
            // complete adjudication here. No fake Chess/Draughts outcomes.
            if (rules != 1) throw new Rejected("board_rules_adjudication_not_implemented");
            table.Rules = rules;
            table.ClearBoard();
            output.Add(Delivery.To(caller.Guid, Wire(33, Int(index), "", BoardRules[rules])));
            AddOtherSeat(table.Seats, caller.Guid, Wire(40, Int(index), "", BoardRules[rules]), output);
        }

        private void BoardStart(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 2);
            int index = TableIndex(args[1], boards.Length);
            BoardTable table = boards[index];
            RequireOwner(table.Seats, caller.Guid);
            if (Occupied(table.Seats) != 2) throw new Rejected("board_requires_two_players");
            if (table.Rules != 1) throw new Rejected("board_select_supported_rules_first");
            if (table.Playing) throw new Rejected("board_match_already_playing");
            table.ClearBoard();
            table.Playing = true;
            output.Add(Delivery.To(caller.Guid, Wire(34, Int(index))));
            AddOtherSeat(table.Seats, caller.Guid, Wire(41, Int(index)), output);
        }

        private void BoardMove(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 3);
            int index = TableIndex(args[1], boards.Length);
            BoardTable table = boards[index];
            int player = RequireSeat(table.Seats, caller.Guid);
            string[] fields = DecodeTokens(args[2], 4);
            int ox = Integer(fields[0]), oy = Integer(fields[1]);
            int x = Integer(fields[2]), y = Integer(fields[3]);
            if (!table.Playing || table.Rules != 1) throw new Rejected("board_no_supported_active_match");
            if (table.Turn != player) throw new Rejected("board_move_out_of_turn");
            if (x < 0 || x >= 3 || y < 0 || y >= 3) throw new Rejected("board_target_out_of_bounds");
            int cell = x * 3 + y; // native TicTacToeInputManager.ApplyMove0x550a10
            if (table.Cells[cell] != '0') throw new Rejected("board_target_occupied");
            table.Cells[cell] = player == 0 ? 'x' : 'o';
            string state;
            if (Won(table.Cells, table.Cells[cell]))
            {
                state = player == 0 ? "P1Wins" : "P2Wins";
                table.Playing = false;
            }
            else if (Full(table.Cells))
            {
                state = "Draw";
                table.Playing = false;
            }
            else
            {
                table.Turn = 1 - player;
                state = table.Turn == 0 ? "P1Turn" : "P2Turn";
            }
            string move = Tokens(Int(ox), Int(oy), Int(x), Int(y));
            // Actor already applied its input:35 checks result only. Rival43
            // decodes/applies the Move, then checks result. Spectator replay
            // initialization is unresolved, so do not broadcast43 blindly.
            output.Add(Delivery.To(caller.Guid, Wire(35, Int(index), "", state, Int(player))));
            AddOtherSeat(table.Seats, caller.Guid, Wire(43, Int(index), "", state, Int(player), move), output);
        }

        private void RemoveBoard(string guid, int index, bool reply, List<Delivery> output)
        {
            BoardTable table = boards[index];
            string rival = OtherSeatGuid(table.Seats, guid);
            RemoveAndCompact(table.Seats, guid);
            table.ClearBoard();
            if (Occupied(table.Seats) == 0) table.Rules = 0;
            if (reply) output.Add(Delivery.To(guid, Wire(36, guid, Int(index))));
            if (rival != null) output.Add(Delivery.To(rival, Wire(42, guid, Int(index))));
            output.Add(Delivery.Others(guid, Wire(39, Int(index), "", BoardData(table))));
        }

        private string BoardSnapshot()
        {
            var fields = new List<string> { "" };
            foreach (BoardTable table in boards)
                fields.Add(table.Rules == 0 ? "0" : "1" + new String(table.Cells));
            // Native37 consumes only state slots1..N-1, skips slotN, then
            // starts the two-GUID-per-table section at N+1. Keep all N slots.
            foreach (BoardTable table in boards)
            {
                fields.Add(table.Seats[0]?.Guid ?? "");
                fields.Add(table.Seats[1]?.Guid ?? "");
            }
            return Wire(37, fields.ToArray());
        }

        private static string BoardData(BoardTable table) => Tokens(BoardRules[table.Rules], "2",
            table.Seats[0]?.Guid ?? "", table.Seats[1]?.Guid ?? "", "2",
            table.Seats[0]?.PlatformId ?? "", table.Seats[1]?.PlatformId ?? "");

        private void DartsJoin(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 2);
            int index = TableIndex(args[1], darts.Length);
            DartsTable table = darts[index];
            if (Seat(table.Seats, caller.Guid) >= 0) throw new Rejected("minigame_already_seated");
            RequireNotSeated(caller.Guid);
            int occupied = Occupied(table.Seats);
            if (occupied == 2)
            {
                output.Add(Delivery.To(caller.Guid, DartsInit(index, "Full", table)));
                return;
            }
            table.Seats[occupied] = caller;
            output.Add(Delivery.To(caller.Guid, DartsInit(index, occupied == 0 ? "Free" : "Awaiting", table)));
            output.Add(Delivery.Others(caller.Guid, Wire(87, "", Int(index), DartsData(table))));
        }

        private void DartsSelect(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 4);
            int index = TableIndex(args[1], darts.Length);
            DartsTable table = darts[index];
            RequireOwner(table.Seats, caller.Guid);
            int rules = Integer(args[2]), players = Integer(args[3]);
            if (rules < 0 || rules >= DartsRules.Length || players < 1 || players > 2)
                throw new Rejected("darts_invalid_lobby_rules_or_player_count");
            if (players < Occupied(table.Seats)) throw new Rejected("darts_mode_has_too_many_seated_players");
            table.Rules = rules;
            table.RequestedPlayers = players;
            output.Add(Delivery.To(caller.Guid, Wire(82, Int(index), Int(players), DartsRules[rules])));
            output.Add(Delivery.Others(caller.Guid, Wire(87, "", Int(index), DartsData(table))));
            AddOtherSeat(table.Seats, caller.Guid, Wire(89, Int(index), "", DartsRules[rules]), output);
        }

        private void RemoveDarts(string guid, int index, bool reply, List<Delivery> output)
        {
            DartsTable table = darts[index];
            string rival = OtherSeatGuid(table.Seats, guid);
            RemoveAndCompact(table.Seats, guid);
            string state = Occupied(table.Seats) == 0 ? "Free" : "Awaiting";
            if (Occupied(table.Seats) == 0) { table.Rules = 0; table.RequestedPlayers = 1; }
            if (reply) output.Add(Delivery.To(guid, Wire(81, Int(index), state)));
            if (rival != null) output.Add(Delivery.To(rival, Wire(88, guid, Int(index), state)));
            output.Add(Delivery.Others(guid, Wire(87, "", Int(index), DartsData(table))));
            if (table.Seats[0] != null)
                output.Add(Delivery.To(table.Seats[0].Guid, DartsSnapshot(table.Seats[0].Guid)));
        }

        private string DartsSnapshot(string guid)
        {
            var fields = new List<string> { guid };
            foreach (DartsTable table in darts) fields.AddRange(DartsBlock(table));
            // End-of-payload drives the native table loop: no extra footer.
            return Wire(86, fields.ToArray());
        }

        private static string DartsInit(int index, string state, DartsTable table)
        {
            var fields = new List<string> { "", Int(index), state };
            fields.AddRange(DartsBlock(table));
            return Wire(80, fields.ToArray());
        }

        private static string DartsData(DartsTable table) => Tokens(DartsRules[table.Rules],
            "Inactive", "0", Int(table.RequestedPlayers), "False");

        private static IEnumerable<string> DartsBlock(DartsTable table)
        {
            yield return DartsData(table);
            yield return Int(Occupied(table.Seats));
            for (int i = 0; i < table.Seats.Length; ++i)
            {
                Identity player = table.Seats[i];
                if (player == null) continue;
                // Lobby-only display seed, not an adjudicated live score.
                int score = table.Rules < 3 ? 301 + table.Rules * 200 : 0;
                yield return Tokens(player.DisplayName, player.PlatformId, player.Guid,
                    Int(score), Int(i), i == 0 ? "red" : "blue");
            }
        }

        private Identity IdentityFor(string guid)
        {
            Identity player = resolveIdentity(guid);
            if (player == null || player.Guid != guid || String.IsNullOrEmpty(player.PlatformId))
                throw new Rejected("minigame_identity_unavailable");
            SafeText(player.Guid); SafeText(player.DisplayName); SafeText(player.PlatformId);
            if (player.Guid.Length > 256 || player.DisplayName.Length > 256 || player.PlatformId.Length > 256)
                throw new Rejected("minigame_identity_too_long");
            return player;
        }

        private void RequireNotSeated(string guid)
        {
            foreach (BoardTable table in boards)
                if (Seat(table.Seats, guid) >= 0) throw new Rejected("minigame_already_seated");
            foreach (DartsTable table in darts)
                if (Seat(table.Seats, guid) >= 0) throw new Rejected("minigame_already_seated");
        }

        private static int Seat(Identity[] seats, string guid)
        {
            for (int i = 0; i < seats.Length; ++i)
                if (seats[i] != null && seats[i].Guid == guid) return i;
            return -1;
        }

        private static int RequireSeat(Identity[] seats, string guid)
        {
            int seat = Seat(seats, guid);
            if (seat < 0) throw new Rejected("minigame_table_not_owned");
            return seat;
        }

        private static void RequireOwner(Identity[] seats, string guid)
        {
            if (RequireSeat(seats, guid) != 0) throw new Rejected("minigame_requires_first_seat");
        }

        private static int Occupied(Identity[] seats) => (seats[0] == null ? 0 : 1) + (seats[1] == null ? 0 : 1);

        private static void RemoveAndCompact(Identity[] seats, string guid)
        {
            int seat = Seat(seats, guid);
            if (seat < 0) return;
            seats[seat] = null;
            if (seats[0] == null) { seats[0] = seats[1]; seats[1] = null; }
        }

        private static void AddOtherSeat(Identity[] seats, string actor, string payload, List<Delivery> output)
        {
            foreach (Identity seat in seats)
                if (seat != null && seat.Guid != actor) output.Add(Delivery.To(seat.Guid, payload));
        }

        private static string OtherSeatGuid(Identity[] seats, string actor)
        {
            foreach (Identity seat in seats)
                if (seat != null && seat.Guid != actor) return seat.Guid;
            return null;
        }

        private static bool Full(char[] cells)
        {
            foreach (char cell in cells) if (cell == '0') return false;
            return true;
        }

        private static bool Won(char[] cells, char mark)
        {
            for (int i = 0; i < 3; ++i)
                if ((cells[i * 3] == mark && cells[i * 3 + 1] == mark && cells[i * 3 + 2] == mark) ||
                    (cells[i] == mark && cells[i + 3] == mark && cells[i + 6] == mark)) return true;
            return (cells[0] == mark && cells[4] == mark && cells[8] == mark) ||
                (cells[2] == mark && cells[4] == mark && cells[6] == mark);
        }

        private static ReadOnlyCollection<Delivery> Freeze(List<Delivery> output) => output.AsReadOnly();
        private static string Int(int value) => value.ToString(Invariant);
        private static string Wire(int opcode, params string[] fields) => Int(opcode) +
            (fields.Length == 0 ? "" : "#" + String.Join("#", fields));

        // EntryData lexical tokens use C# UTF16 String.Length, not UTF8 bytes.
        // Arrays concatenate token(count) followed by element tokens. The
        // fixed BoardData schema above explicitly includes both two-seat arrays.
        private static string Tokens(params string[] fields)
        {
            var result = new StringBuilder();
            foreach (string field in fields)
            {
                SafeText(field);
                if (field.Length > Char.MaxValue - 0x24) throw new Rejected("entrydata_token_too_long");
                result.Append((char)(field.Length + 0x24));
                result.Append(field);
            }
            return result.ToString();
        }

        private static string[] DecodeTokens(string text, int count)
        {
            if (text == null || text.Length > 8192) throw new Rejected("invalid_entrydata_size");
            var fields = new string[count];
            int cursor = 0;
            for (int i = 0; i < fields.Length; ++i)
            {
                if (cursor >= text.Length) throw new Rejected("entrydata_missing_field");
                int length = text[cursor++] - 0x24;
                if (length < 0 || length > text.Length - cursor) throw new Rejected("entrydata_invalid_length");
                fields[i] = text.Substring(cursor, length);
                cursor += length;
            }
            if (cursor != text.Length) throw new Rejected("entrydata_trailing_fields");
            return fields;
        }

        private static void SafeText(string value)
        {
            if (value == null || value.IndexOf('#') >= 0 || value.IndexOf('\0') >= 0)
                throw new Rejected("minigame_text_cannot_be_framed");
        }

        private static int Integer(string value)
        {
            if (!Int32.TryParse(value, NumberStyles.Integer, Invariant, out int result))
                throw new Rejected("minigame_invalid_int32");
            return result;
        }

        private static int TableIndex(string value, int count)
        {
            int index = Integer(value);
            if (index < 0 || index >= count) throw new Rejected("minigame_table_not_in_scene");
            return index;
        }

        private static void Count(string[] args, int count)
        {
            if (args.Length != count) throw new Rejected("minigame_wrong_field_count");
        }

        private static float FiniteFloat(string value)
        {
            if (!Single.TryParse(value, NumberStyles.Float, Invariant, out float number) ||
                Single.IsNaN(number) || Single.IsInfinity(number)) throw new Rejected("minigame_invalid_float");
            return number;
        }
    }
}
