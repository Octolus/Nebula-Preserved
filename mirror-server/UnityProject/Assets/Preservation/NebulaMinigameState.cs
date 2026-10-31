using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.Text;

namespace NebulaPreservation
{
    // Pure replacement policy, not recovered original server source.
    // Wire/DTO constraints: docs/research/minigame-contracts.json and
    // tcp-contracts.json; source binary SHA256
    // c4dd5db599e5e5ce4adf25f09ffe70ad10e0928adf6a2e862176d537026b44ac.
    // No Unity, Mirror, filesystem, clock, RNG, sockets or background work.
    //
    // Role of this server, per the client receivers: seat/lobby authority and
    // relay. Pool/bowling/darts physics, scoring and turn rotation are computed
    // by the clients; the server only acknowledges the actor (OK/echo) and
    // forwards the actor's values to the other participants. Board games are
    // the exception: the client never decides a result (CheckNewMatchState
    // 0x53cbe0 only consumes the server's GameState), so the board state is
    // tracked here to report wins/draws and to answer snapshot37.
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

        private const int TicTacToe = 1, Chess = 2, Draughts = 3;

        private sealed class BoardTable
        {
            public readonly Identity[] Seats = new Identity[2];
            public char[] Cells = new char[9];
            public readonly bool[] Moved = new bool[64];
            public int Rules;
            public int Turn;
            public bool Playing;
            public int EnPassant = -1;
            public int Chain = -1;
            public BoardTable() { ClearBoard(); }
            // Initial layouts mirror ChessBoard.CreateAllPieces 0x52e3d0 and
            // DraughtsBoard.CreateAllPieces 0x536e70 in snapshot notation
            // (BoardTableSnapshot chars, index = x*8+y).
            public void ClearBoard()
            {
                Turn = 0;
                Playing = false;
                EnPassant = -1;
                Chain = -1;
                Array.Clear(Moved, 0, Moved.Length);
                if (Rules == Chess)
                    Cells = ("rnbqkbnr" + "pppppppp" + "00000000" + "00000000" +
                        "00000000" + "00000000" + "PPPPPPPP" + "RNBQKBNR").ToCharArray();
                else if (Rules == Draughts)
                    Cells = ("R0R0R0R0" + "0R0R0R0R" + "R0R0R0R0" + "00000000" +
                        "00000000" + "0r0r0r0r" + "r0r0r0r0" + "0r0r0r0r").ToCharArray();
                else
                    Cells = "000000000".ToCharArray();
            }
        }

        private sealed class DartsTable
        {
            public readonly Identity[] Seats = new Identity[2];
            public int Rules;
            public int RequestedPlayers = 1;
            public bool ModeSelected;
            // Scores and turns stay client-side (DartsRules*.ProcessShot);
            // Playing only drives TableData.isActive and seat admission.
            public bool Playing;
        }

        private sealed class PoolTable
        {
            public readonly Identity[] Seats = new Identity[2];
            public int Rules = -1;
            public int Players;
            public bool Playing;
        }

        private sealed class BowlingLane
        {
            public readonly Identity[] Seats = new Identity[BowlingSeats];
            public readonly bool[] Ready = new bool[BowlingSeats];
            public int State; // BowlingGameManager.LaneState index
            public int TurnIndex;
        }

        private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;
        private static readonly string[] BoardRules = { "None", "TicTacToe", "Chess", "Draughts" };
        private static readonly string[] DartsRules = { "Game301", "Game501", "Game701", "Cricket", "AroundTheClock" };
        private static readonly string[] LaneStates = { "Free", "Rejected", "Awaiting", "Ready", "Playing" };
        private const int LaneFree = 0, LaneAwaiting = 2, LaneReady = 3, LanePlaying = 4;
        // UIBowlingMain has four UIBowlingMainEntry rows per lane; the panel
        // array keeps empty seats because Get_StartGame 0x548740 uses array
        // indices as scene seat indices.
        private const int BowlingSeats = 4;
        private const int PoolMaxBalls = 16;
        private const int BowlingPins = 10;
        private readonly BoardTable[] boards;
        private readonly DartsTable[] darts;
        private readonly PoolTable[] pools;
        private readonly BowlingLane[] lanes;
        private readonly Func<string, Identity> resolveIdentity;

        public bool ReadyForOriginalServerParity => false;
        public int BoardTableCount => boards.Length;
        public int DartsTableCount => darts.Length;
        public int PoolTableCount => pools.Length;
        public int BowlingLaneCount => lanes.Length;

        // Counts must describe the loaded scene. The complete Nexus inventory
        // confirms 0/0. The Bowling logic prefab configures Pool 9 (active),
        // Bowling 12 (active) and Darts 3 (manager activeSelf=false); positive
        // counts still require the host to pass them explicitly.
        public NebulaMinigameState(int boardTableCount, int dartsTableCount,
            Func<string, Identity> resolveIdentity)
            : this(boardTableCount, dartsTableCount, 0, 0, resolveIdentity) { }

        public NebulaMinigameState(int boardTableCount, int dartsTableCount, int poolTableCount,
            int bowlingLaneCount, Func<string, Identity> resolveIdentity)
        {
            if (boardTableCount < 0 || boardTableCount > 64 || dartsTableCount < 0 || dartsTableCount > 64 ||
                poolTableCount < 0 || poolTableCount > 64 || bowlingLaneCount < 0 || bowlingLaneCount > 64)
                throw new ArgumentOutOfRangeException("table counts must be between 0 and 64");
            this.resolveIdentity = resolveIdentity ?? throw new ArgumentNullException(nameof(resolveIdentity));
            boards = new BoardTable[boardTableCount];
            darts = new DartsTable[dartsTableCount];
            pools = new PoolTable[poolTableCount];
            lanes = new BowlingLane[bowlingLaneCount];
            for (int i = 0; i < boards.Length; ++i) boards[i] = new BoardTable();
            for (int i = 0; i < darts.Length; ++i) darts[i] = new DartsTable();
            for (int i = 0; i < pools.Length; ++i) pools[i] = new PoolTable();
            for (int i = 0; i < lanes.Length; ++i) lanes[i] = new BowlingLane();
        }

        // Only opcodes with a client sender are claimed. 38/58/67/75/83 have
        // no sender; 39-43, 59-63, 72-79 and 87-91 are clientbound only.
        public bool Handles(int opcode) => (opcode >= 32 && opcode <= 37) || (opcode >= 51 && opcode <= 57) ||
            (opcode >= 64 && opcode <= 66) || (opcode >= 68 && opcode <= 71) ||
            (opcode >= 80 && opcode <= 82) || (opcode >= 84 && opcode <= 86);

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
                case 51: PoolJoin(caller, args, output); break;
                case 52:
                    Count(args, 2);
                    int pi = TableIndex(args[1], pools.Length);
                    RequireSeat(pools[pi].Seats, caller.Guid);
                    RemovePool(caller.Guid, pi, true, output);
                    break;
                case 53: PoolSelect(caller, args, output); break;
                case 54: PoolStart(caller, args, output); break;
                case 55: PoolShot(caller, args, output); break;
                case 56: PoolBalls(caller, args, output); break;
                case 57: PoolFoul(caller, args, output); break;
                case 64: BowlingJoin(caller, args, output); break;
                case 65:
                    Count(args, 3);
                    if (args[1] != caller.PlatformId) throw new Rejected("bowling_platform_id_not_owned");
                    int li = TableIndex(args[2], lanes.Length);
                    RequireSeat(lanes[li].Seats, caller.Guid);
                    RemoveBowling(caller.Guid, li, true, output);
                    break;
                case 66: BowlingReady(caller, args, output); break;
                case 68: BowlingShot(caller, args, output); break;
                case 69: BowlingPinsMessage(caller, args, output); break;
                case 70: BowlingTurn(caller, args, output); break;
                case 71:
                    Count(args, 2);
                    int si = TableIndex(args[1], lanes.Length);
                    output.Add(Delivery.To(caller.Guid, Wire(71, caller.Guid, Int(si), Panel(lanes[si], -1))));
                    break;
                case 80: DartsJoin(caller, args, output); break;
                case 81:
                    Count(args, 2);
                    int di = TableIndex(args[1], darts.Length);
                    RequireSeat(darts[di].Seats, caller.Guid);
                    RemoveDarts(caller.Guid, di, true, output);
                    break;
                case 82: DartsSelect(caller, args, output); break;
                case 84: DartsStart(caller, args, output); break;
                case 85: DartsMove(caller, args, output); break;
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
            for (int i = 0; i < pools.Length; ++i)
                if (Seat(pools[i].Seats, guid) >= 0) RemovePool(guid, i, false, output);
            for (int i = 0; i < lanes.Length; ++i)
                if (Seat(lanes[i].Seats, guid) >= 0) RemoveBowling(guid, i, false, output);
            return Freeze(output);
        }

        // ---------------------------------------------------------------- Board

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
            // BoardGamesManager.GameRules: TicTacToe1, Chess2, Draughts3.
            if (rules < TicTacToe || rules > Draughts) throw new Rejected("board_invalid_rules");
            table.Rules = rules;
            table.ClearBoard();
            output.Add(Delivery.To(caller.Guid, Wire(33, Int(index), "", BoardRules[rules])));
            AddOtherSeat(table.Seats, caller.Guid, Wire(40, Int(index), "", BoardRules[rules]), output);
        }

        // Either seat may start: SpaceGameManager.OnClickStartGame and
        // OnClickJoinMatch share 0x575790, which calls Send_StartGame.
        private void BoardStart(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 2);
            int index = TableIndex(args[1], boards.Length);
            BoardTable table = boards[index];
            RequireSeat(table.Seats, caller.Guid);
            if (Occupied(table.Seats) != 2) throw new Rejected("board_requires_two_players");
            if (table.Rules < TicTacToe) throw new Rejected("board_select_rules_first");
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
            if (!table.Playing || table.Rules < TicTacToe) throw new Rejected("board_no_active_match");
            if (table.Turn != player) throw new Rejected("board_move_out_of_turn");
            string state;
            if (table.Rules == TicTacToe) state = TicTacToeMove(table, player, x, y);
            else if (table.Rules == Chess) state = ChessMove(table, player, ox, oy, x, y);
            else state = DraughtsMove(table, player, ox, oy, x, y);
            string move = Tokens(Int(ox), Int(oy), Int(x), Int(y));
            // Actor already applied its input: 35 checks result only. Rival 43
            // decodes/applies the Move, then checks result. Spectator replay
            // initialization is unresolved, so do not broadcast 43 blindly.
            output.Add(Delivery.To(caller.Guid, Wire(35, Int(index), "", state, Int(player))));
            AddOtherSeat(table.Seats, caller.Guid, Wire(43, Int(index), "", state, Int(player), move), output);
        }

        private static string TicTacToeMove(BoardTable table, int player, int x, int y)
        {
            if (x < 0 || x >= 3 || y < 0 || y >= 3) throw new Rejected("board_target_out_of_bounds");
            int cell = x * 3 + y; // native TicTacToeInputManager.ApplyMove 0x550a10
            if (table.Cells[cell] != '0') throw new Rejected("board_target_occupied");
            table.Cells[cell] = player == 0 ? 'x' : 'o';
            if (Won(table.Cells, table.Cells[cell])) return Finish(table, player == 0 ? "P1Wins" : "P2Wins");
            if (Full(table.Cells)) return Finish(table, "Draw");
            return NextTurn(table, 1 - player);
        }

        private static string Finish(BoardTable table, string state)
        {
            table.Playing = false;
            return state;
        }

        private static string NextTurn(BoardTable table, int player)
        {
            table.Turn = player;
            return player == 0 ? "P1Turn" : "P2Turn";
        }

        private void RemoveBoard(string guid, int index, bool reply, List<Delivery> output)
        {
            BoardTable table = boards[index];
            string rival = OtherSeatGuid(table.Seats, guid);
            RemoveAndCompact(table.Seats, guid);
            if (Occupied(table.Seats) == 0) table.Rules = 0;
            table.ClearBoard();
            if (reply) output.Add(Delivery.To(guid, Wire(36, guid, Int(index))));
            if (rival != null) output.Add(Delivery.To(rival, Wire(42, guid, Int(index))));
            output.Add(Delivery.Others(guid, Wire(39, Int(index), "", BoardData(table))));
        }

        private string BoardSnapshot()
        {
            var fields = new List<string> { "" };
            // BoardTablesnapshot: one rules digit, then concrete board text
            // (BoardGamesTable.DeserializeTable 0x541310).
            foreach (BoardTable table in boards)
                fields.Add(table.Rules == 0 ? "0" : Int(table.Rules) + new String(table.Cells));
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

        // --------------------------------------------------------------- Chess
        // Client rules recovered from ChessPiece*/ChessBoard/ChessLogic:
        // player0 = White (lowercase, rows 0-1, moves +x), player1 = Black.
        // Castling moves the rook to y5/y3, en passant removes (originX,
        // targetY), pawns promote to Queen on x0/x7 (ChessLogic.MakeMove
        // 0x533e80 -> CreatePiece(4,...)). The client only offers moves that
        // pass IsMoveSaveForKing 0x530050 and never detects mate itself.

        private static string ChessMove(BoardTable table, int player, int ox, int oy, int x, int y)
        {
            if (!InBoard(ox, oy) || !InBoard(x, y) || (ox == x && oy == y)) throw new Rejected("board_target_out_of_bounds");
            char piece = table.Cells[ox * 8 + oy];
            if (ChessOwner(piece) != player) throw new Rejected("board_origin_not_owned");
            if (ChessOwner(table.Cells[x * 8 + y]) == player) throw new Rejected("board_target_occupied");
            int ep = table.EnPassant;
            ApplyChess(table.Cells, table.Moved, ref ep, ox, oy, x, y);
            table.EnPassant = ep;
            int next = 1 - player;
            if (!HasLegalChessMove(table.Cells, table.Moved, table.EnPassant, next))
                return Finish(table, InCheck(table.Cells, next) ? (player == 0 ? "P1Wins" : "P2Wins") : "Draw");
            return NextTurn(table, next);
        }

        private static bool InBoard(int x, int y) => x >= 0 && x < 8 && y >= 0 && y < 8;
        private static int ChessOwner(char c) => c == '0' ? -1 : (c >= 'a' && c <= 'z' ? 0 : 1);
        private static char Kind(char c) => Char.ToLowerInvariant(c);

        private static void ApplyChess(char[] b, bool[] moved, ref int ep, int ox, int oy, int x, int y)
        {
            int o = ox * 8 + oy, t = x * 8 + y;
            char c = b[o];
            int side = ChessOwner(c);
            char kind = Kind(c);
            if (kind == 'p' && oy != y && b[t] == '0' && t == ep) b[ox * 8 + y] = '0';
            if (kind == 'k' && ox == x && Math.Abs(y - oy) == 2)
            {
                int from = ox * 8 + (y > oy ? 7 : 0), to = ox * 8 + (y > oy ? 5 : 3);
                b[to] = b[from]; b[from] = '0'; moved[to] = true; moved[from] = false;
            }
            b[t] = c; b[o] = '0'; moved[t] = true; moved[o] = false;
            ep = -1;
            if (kind == 'p' && Math.Abs(x - ox) == 2) ep = ((ox + x) / 2) * 8 + oy;
            if (kind == 'p' && (x == 7 || x == 0)) b[t] = side == 0 ? 'q' : 'Q';
        }

        private static readonly int[,] KnightSteps = { {1,2},{2,1},{-1,2},{-2,1},{1,-2},{2,-1},{-1,-2},{-2,-1} };
        private static readonly int[,] KingSteps = { {1,0},{-1,0},{0,1},{0,-1},{1,1},{1,-1},{-1,1},{-1,-1} };

        private static bool Attacked(char[] b, int x, int y, int by)
        {
            int d = by == 0 ? 1 : -1;
            for (int dy = -1; dy <= 1; dy += 2)
            {
                int px = x - d, py = y + dy;
                if (InBoard(px, py) && ChessOwner(b[px * 8 + py]) == by && Kind(b[px * 8 + py]) == 'p') return true;
            }
            for (int i = 0; i < 8; ++i)
            {
                int nx = x + KnightSteps[i, 0], ny = y + KnightSteps[i, 1];
                if (InBoard(nx, ny) && ChessOwner(b[nx * 8 + ny]) == by && Kind(b[nx * 8 + ny]) == 'n') return true;
                int kx = x + KingSteps[i, 0], ky = y + KingSteps[i, 1];
                if (InBoard(kx, ky) && ChessOwner(b[kx * 8 + ky]) == by && Kind(b[kx * 8 + ky]) == 'k') return true;
            }
            for (int i = 0; i < 8; ++i)
            {
                int dx = KingSteps[i, 0], dy = KingSteps[i, 1];
                bool straight = dx == 0 || dy == 0;
                for (int sx = x + dx, sy = y + dy; InBoard(sx, sy); sx += dx, sy += dy)
                {
                    char c = b[sx * 8 + sy];
                    if (c == '0') continue;
                    char k = Kind(c);
                    if (ChessOwner(c) == by && (k == 'q' || (straight ? k == 'r' : k == 'b'))) return true;
                    break;
                }
            }
            return false;
        }

        private static bool InCheck(char[] b, int side)
        {
            for (int i = 0; i < 64; ++i)
                if (ChessOwner(b[i]) == side && Kind(b[i]) == 'k') return Attacked(b, i / 8, i % 8, 1 - side);
            return false;
        }

        private static bool HasLegalChessMove(char[] b, bool[] moved, int ep, int side)
        {
            var targets = new List<int>();
            for (int o = 0; o < 64; ++o)
            {
                if (ChessOwner(b[o]) != side) continue;
                targets.Clear();
                ChessCandidates(b, moved, ep, side, o, targets);
                foreach (int t in targets)
                {
                    char[] copy = (char[])b.Clone();
                    bool[] movedCopy = (bool[])moved.Clone();
                    int epCopy = ep;
                    ApplyChess(copy, movedCopy, ref epCopy, o / 8, o % 8, t / 8, t % 8);
                    if (!InCheck(copy, side)) return true;
                }
            }
            return false;
        }

        private static void ChessCandidates(char[] b, bool[] moved, int ep, int side, int o, List<int> targets)
        {
            int x = o / 8, y = o % 8;
            switch (Kind(b[o]))
            {
                case 'p':
                {
                    int d = side == 0 ? 1 : -1, start = side == 0 ? 1 : 6;
                    if (InBoard(x + d, y) && b[(x + d) * 8 + y] == '0')
                    {
                        targets.Add((x + d) * 8 + y);
                        if (x == start && b[(x + 2 * d) * 8 + y] == '0') targets.Add((x + 2 * d) * 8 + y);
                    }
                    for (int dy = -1; dy <= 1; dy += 2)
                    {
                        if (!InBoard(x + d, y + dy)) continue;
                        int t = (x + d) * 8 + y + dy;
                        if (ChessOwner(b[t]) == 1 - side || (t == ep && b[t] == '0')) targets.Add(t);
                    }
                    break;
                }
                case 'n':
                    for (int i = 0; i < 8; ++i) Step(b, side, x + KnightSteps[i, 0], y + KnightSteps[i, 1], targets);
                    break;
                case 'k':
                {
                    for (int i = 0; i < 8; ++i) Step(b, side, x + KingSteps[i, 0], y + KingSteps[i, 1], targets);
                    int home = side == 0 ? 0 : 7;
                    if (x == home && y == 4 && !moved[o] && !Attacked(b, x, 4, 1 - side))
                    {
                        if (CastleRook(b, moved, side, home * 8 + 7) && b[home * 8 + 5] == '0' && b[home * 8 + 6] == '0' &&
                            !Attacked(b, home, 5, 1 - side) && !Attacked(b, home, 6, 1 - side)) targets.Add(home * 8 + 6);
                        if (CastleRook(b, moved, side, home * 8) && b[home * 8 + 1] == '0' && b[home * 8 + 2] == '0' &&
                            b[home * 8 + 3] == '0' && !Attacked(b, home, 3, 1 - side) && !Attacked(b, home, 2, 1 - side))
                            targets.Add(home * 8 + 2);
                    }
                    break;
                }
                default:
                {
                    char k = Kind(b[o]);
                    for (int i = 0; i < 8; ++i)
                    {
                        int dx = KingSteps[i, 0], dy = KingSteps[i, 1];
                        bool straight = dx == 0 || dy == 0;
                        if (k == 'r' && !straight || k == 'b' && straight) continue;
                        for (int sx = x + dx, sy = y + dy; InBoard(sx, sy); sx += dx, sy += dy)
                        {
                            int owner = ChessOwner(b[sx * 8 + sy]);
                            if (owner == side) break;
                            targets.Add(sx * 8 + sy);
                            if (owner >= 0) break;
                        }
                    }
                    break;
                }
            }
        }

        private static bool CastleRook(char[] b, bool[] moved, int side, int at) =>
            ChessOwner(b[at]) == side && Kind(b[at]) == 'r' && !moved[at];

        private static void Step(char[] b, int side, int x, int y, List<int> targets)
        {
            if (InBoard(x, y) && ChessOwner(b[x * 8 + y]) != side) targets.Add(x * 8 + y);
        }

        // ------------------------------------------------------------ Draughts
        // Client rules recovered from DraughtsPieceRegular/King 0x54fb00..
        // 0x54ffb0, DraughtsInputManager 0x538550/0x5395c0, DraughtsLogic
        // 0x54f510: player0 = Red (uppercase, rows 0-2, moves +x), single-step
        // diagonal moves, Regular pieces move/capture forward only, Kings in
        // all four diagonals, capture is mandatory, a capture continues while
        // the landed piece (after promotion on x0/x7) can capture again; each
        // jump is a separate request35.

        private static string DraughtsMove(BoardTable table, int player, int ox, int oy, int x, int y)
        {
            char[] b = table.Cells;
            if (!InBoard(ox, oy) || !InBoard(x, y)) throw new Rejected("board_target_out_of_bounds");
            int o = ox * 8 + oy, t = x * 8 + y;
            if (DraughtsOwner(b[o]) != player) throw new Rejected("board_origin_not_owned");
            if (b[t] != '0') throw new Rejected("board_target_occupied");
            int dx = x - ox, dy = y - oy, distance = Math.Abs(dx);
            if (distance != Math.Abs(dy) || distance < 1 || distance > 2) throw new Rejected("board_illegal_move");
            if (table.Chain >= 0 && (o != table.Chain || distance != 2)) throw new Rejected("board_capture_chain_required");
            if (distance == 2)
            {
                int middle = (ox + dx / 2) * 8 + oy + dy / 2;
                if (DraughtsOwner(b[middle]) != 1 - player) throw new Rejected("board_illegal_move");
                b[middle] = '0';
            }
            b[t] = b[o];
            b[o] = '0';
            if ((b[t] == 'R' || b[t] == 'r') && (x == 7 || x == 0)) b[t] = player == 0 ? 'K' : 'k';
            if (distance == 2 && CanCapture(b, t))
            {
                table.Chain = t;
                return NextTurn(table, player);
            }
            table.Chain = -1;
            int next = 1 - player;
            if (!HasDraughtsMove(b, next)) return Finish(table, player == 0 ? "P1Wins" : "P2Wins");
            return NextTurn(table, next);
        }

        private static int DraughtsOwner(char c) => c == '0' ? -1 : (c >= 'A' && c <= 'Z' ? 0 : 1);

        private static bool CanCapture(char[] b, int at)
        {
            int side = DraughtsOwner(b[at]), x = at / 8, y = at % 8;
            bool king = b[at] == 'K' || b[at] == 'k';
            for (int i = 4; i < 8; ++i)
            {
                int dx = KingSteps[i, 0], dy = KingSteps[i, 1];
                if (!king && dx != (side == 0 ? 1 : -1)) continue;
                if (InBoard(x + 2 * dx, y + 2 * dy) && DraughtsOwner(b[(x + dx) * 8 + y + dy]) == 1 - side &&
                    b[(x + 2 * dx) * 8 + y + 2 * dy] == '0') return true;
            }
            return false;
        }

        private static bool HasDraughtsMove(char[] b, int side)
        {
            for (int at = 0; at < 64; ++at)
            {
                if (DraughtsOwner(b[at]) != side) continue;
                if (CanCapture(b, at)) return true;
                int x = at / 8, y = at % 8;
                bool king = b[at] == 'K' || b[at] == 'k';
                for (int i = 4; i < 8; ++i)
                {
                    int dx = KingSteps[i, 0], dy = KingSteps[i, 1];
                    if (!king && dx != (side == 0 ? 1 : -1)) continue;
                    if (InBoard(x + dx, y + dy) && b[(x + dx) * 8 + y + dy] == '0') return true;
                }
            }
            return false;
        }

        // ---------------------------------------------------------------- Darts

        private void DartsJoin(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 2);
            int index = TableIndex(args[1], darts.Length);
            DartsTable table = darts[index];
            if (Seat(table.Seats, caller.Guid) >= 0) throw new Rejected("minigame_already_seated");
            RequireNotSeated(caller.Guid);
            int occupied = Occupied(table.Seats);
            if (occupied == 2 || table.Playing || (occupied == 1 && table.ModeSelected && table.RequestedPlayers == 1))
            {
                output.Add(Delivery.To(caller.Guid, DartsBlockMessage(80, index, "Full", table)));
                return;
            }
            table.Seats[occupied] = caller;
            output.Add(Delivery.To(caller.Guid, DartsBlockMessage(80, index, occupied == 0 ? "Free" : "Awaiting", table)));
            output.Add(Delivery.Others(caller.Guid, Wire(87, "", Int(index), DartsData(table))));
        }

        private void DartsSelect(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 4);
            int index = TableIndex(args[1], darts.Length);
            DartsTable table = darts[index];
            RequireOwner(table.Seats, caller.Guid);
            if (table.Playing) throw new Rejected("darts_match_already_playing");
            int rules = Integer(args[2]), players = Integer(args[3]);
            if (rules < 0 || rules >= DartsRules.Length || players < 1 || players > 2)
                throw new Rejected("darts_invalid_lobby_rules_or_player_count");
            if (players < Occupied(table.Seats)) throw new Rejected("darts_mode_has_too_many_seated_players");
            table.Rules = rules;
            table.RequestedPlayers = players;
            table.ModeSelected = true;
            output.Add(Delivery.To(caller.Guid, Wire(82, Int(index), Int(players), DartsRules[rules])));
            output.Add(Delivery.Others(caller.Guid, Wire(87, "", Int(index), DartsData(table))));
            AddOtherSeat(table.Seats, caller.Guid, Wire(89, Int(index), "", DartsRules[rules]), output);
        }

        // Start84/90 decode a TableBlock and run DartsGameTable.Get_StartGame
        // 0x55e5c0 (local rules/turns); either seat may start (0x575790).
        private void DartsStart(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 2);
            int index = TableIndex(args[1], darts.Length);
            DartsTable table = darts[index];
            RequireSeat(table.Seats, caller.Guid);
            if (!table.ModeSelected) throw new Rejected("darts_select_rules_first");
            if (Occupied(table.Seats) != table.RequestedPlayers) throw new Rejected("darts_waiting_for_players");
            table.Playing = true;
            output.Add(Delivery.To(caller.Guid, DartsBlockMessage(84, index, null, table)));
            AddOtherSeat(table.Seats, caller.Guid, DartsBlockMessage(90, index, null, table), output);
            output.Add(Delivery.Others(caller.Guid, Wire(87, "", Int(index), DartsData(table))));
        }

        // DartsRules.FixedUpdate 0x569e10 sends the shot and stays in
        // Pointing(4); only the server echo (Get_MakeMove 0x55b950 ->
        // MakePassiveMove 0x56c670) advances the shooter to Shoting(5). The
        // shot (including client-randomized deflection) is therefore echoed
        // as 85 to the shooter and relayed as 91 to the rival seat.
        private void DartsMove(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 3);
            int index = TableIndex(args[1], darts.Length);
            DartsTable table = darts[index];
            RequireSeat(table.Seats, caller.Guid);
            if (!table.Playing) throw new Rejected("darts_no_active_match");
            foreach (string number in DecodeTokens(args[2], 5)) FiniteFloat(number);
            output.Add(Delivery.To(caller.Guid, Wire(85, "", Int(index), args[2])));
            AddOtherSeat(table.Seats, caller.Guid, Wire(91, "", Int(index), args[2]), output);
        }

        private void RemoveDarts(string guid, int index, bool reply, List<Delivery> output)
        {
            DartsTable table = darts[index];
            string rival = OtherSeatGuid(table.Seats, guid);
            RemoveAndCompact(table.Seats, guid);
            table.Playing = false;
            string state = Occupied(table.Seats) == 0 ? "Free" : "Awaiting";
            if (Occupied(table.Seats) == 0) { table.Rules = 0; table.RequestedPlayers = 1; table.ModeSelected = false; }
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

        // 80: unread#table#state#block; 84/90: table#block.
        private static string DartsBlockMessage(int opcode, int index, string state, DartsTable table)
        {
            var fields = new List<string>();
            if (state != null) { fields.Add(""); fields.Add(Int(index)); fields.Add(state); }
            else fields.Add(Int(index));
            fields.AddRange(DartsBlock(table));
            return Wire(opcode, fields.ToArray());
        }

        private static string DartsData(DartsTable table) => Tokens(DartsRules[table.Rules],
            table.Playing ? "StartGame" : "Inactive", "0", Int(table.RequestedPlayers), table.Playing ? "True" : "False");

        private static IEnumerable<string> DartsBlock(DartsTable table)
        {
            yield return DartsData(table);
            yield return Int(Occupied(table.Seats));
            for (int i = 0; i < table.Seats.Length; ++i)
            {
                Identity player = table.Seats[i];
                if (player == null) continue;
                // Display seed only; live scores are computed by client rules.
                int score = table.Rules < 3 ? 301 + table.Rules * 200 : 0;
                yield return Tokens(player.DisplayName, player.PlatformId, player.Guid,
                    Int(score), Int(i), i == 0 ? "red" : "blue");
            }
        }

        // ----------------------------------------------------------------- Pool
        // PoolGameManager.Get_InitializeGame 0x5995f0: Free opens rules menu,
        // Awaiting reads rivalName/rulesID and shows the join menu, Full and
        // Playing show the busy menu. There is no init/select OneWay opcode;
        // the owner learns about the rival through StartGameOneWay60.

        private void PoolJoin(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 2);
            int index = TableIndex(args[1], pools.Length);
            PoolTable table = pools[index];
            if (Seat(table.Seats, caller.Guid) >= 0) throw new Rejected("minigame_already_seated");
            RequireNotSeated(caller.Guid);
            int occupied = Occupied(table.Seats);
            if (occupied == 0)
            {
                table.Seats[0] = caller;
                output.Add(Delivery.To(caller.Guid, Wire(51, "", Int(index), "Free", "", "0")));
                return;
            }
            if (occupied == 1 && !table.Playing && table.Rules >= 0 && table.Players == 2)
            {
                table.Seats[1] = caller;
                output.Add(Delivery.To(caller.Guid, Wire(51, "", Int(index), "Awaiting",
                    table.Seats[0].DisplayName, Int(table.Rules))));
                return;
            }
            output.Add(Delivery.To(caller.Guid, Wire(51, "", Int(index), table.Playing ? "Playing" : "Full",
                "", Int(Math.Max(table.Rules, 0)))));
        }

        // Send_SelectGame coroutine 0x5a9e70: rules0 is single-player practice,
        // other rules are two-player. Reply53 field2 is the player count.
        private void PoolSelect(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 4);
            int index = TableIndex(args[1], pools.Length);
            PoolTable table = pools[index];
            RequireOwner(table.Seats, caller.Guid);
            if (table.Playing) throw new Rejected("pool_match_already_playing");
            if (Occupied(table.Seats) != 1) throw new Rejected("pool_rival_already_seated");
            int rules = Integer(args[2]), players = Integer(args[3]);
            if (rules < 0 || rules > 2 || players != (rules == 0 ? 1 : 2))
                throw new Rejected("pool_invalid_rules_or_player_count");
            table.Rules = rules;
            table.Players = players;
            output.Add(Delivery.To(caller.Guid, Wire(53, "", Int(index), Int(players))));
        }

        // PoolGameTable.Get_StartGame 0x59bf20: role "playerOne" selects
        // local seat0, any other role seat1; optional field2 is rival name.
        private void PoolStart(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 3);
            int index = TableIndex(args[1], pools.Length);
            PoolTable table = pools[index];
            int seat = RequireSeat(table.Seats, caller.Guid);
            if (table.Rules < 0) throw new Rejected("pool_select_rules_first");
            if (Integer(args[2]) != table.Players || Occupied(table.Seats) != table.Players)
                throw new Rejected("pool_waiting_for_players");
            table.Playing = true;
            Identity rival = table.Seats[1 - seat];
            output.Add(Delivery.To(caller.Guid, rival == null ? Wire(54, Int(index), PoolRole(seat)) :
                Wire(54, Int(index), PoolRole(seat), rival.DisplayName)));
            if (rival != null)
                output.Add(Delivery.To(rival.Guid, Wire(60, Int(index), PoolRole(1 - seat), caller.DisplayName)));
        }

        private static string PoolRole(int seat) => seat == 0 ? "playerOne" : "playerTwo";

        private PoolTable ActivePool(Identity caller, string table, out int index)
        {
            index = TableIndex(table, pools.Length);
            PoolTable pool = pools[index];
            RequireSeat(pool.Seats, caller.Guid);
            if (!pool.Playing) throw new Rejected("pool_no_active_match");
            return pool;
        }

        // Shot/result/foul: actor receives the exact "OK" acknowledgement its
        // BallMoveWaitServer state waits for; the rival receives the replay
        // layout (request GUID and, for 56, block-word count removed).
        private void PoolShot(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 7);
            PoolTable table = ActivePool(caller, args[1], out int index);
            for (int i = 2; i < 7; ++i) FiniteFloat(args[i]);
            output.Add(Delivery.To(caller.Guid, Wire(55, Int(index), "OK")));
            AddOtherSeat(table.Seats, caller.Guid, Wire(61, Int(index), args[2], args[3], args[4], args[5], args[6]), output);
        }

        private void PoolBalls(Identity caller, string[] args, List<Delivery> output)
        {
            if (args.Length < 4) throw new Rejected("minigame_wrong_field_count");
            PoolTable table = ActivePool(caller, args[1], out int index);
            Integer(args[2]);
            int balls = Integer(args[3]);
            if (balls < 0 || balls > PoolMaxBalls) throw new Rejected("pool_invalid_ball_count");
            Count(args, 6 + 3 * balls);
            var fields = new List<string> { Int(index), Int(balls) };
            for (int i = 0; i < 2 * balls; ++i) { FiniteFloat(args[4 + i]); fields.Add(args[4 + i]); }
            for (int i = 0; i < balls + 2; ++i) { Integer(args[4 + 2 * balls + i]); fields.Add(args[4 + 2 * balls + i]); }
            output.Add(Delivery.To(caller.Guid, Wire(56, Int(index), "OK")));
            AddOtherSeat(table.Seats, caller.Guid, Wire(62, fields.ToArray()), output);
        }

        private void PoolFoul(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 4);
            PoolTable table = ActivePool(caller, args[1], out int index);
            FiniteFloat(args[2]); FiniteFloat(args[3]);
            output.Add(Delivery.To(caller.Guid, Wire(57, Int(index), "OK")));
            AddOtherSeat(table.Seats, caller.Guid, Wire(63, Int(index), args[2], args[3]), output);
        }

        // Reply52 payload is ignored (0x5457f0); rival gets RivalGone59.
        private void RemovePool(string guid, int index, bool reply, List<Delivery> output)
        {
            PoolTable table = pools[index];
            string rival = OtherSeatGuid(table.Seats, guid);
            RemoveAndCompact(table.Seats, guid);
            table.Playing = false;
            if (Occupied(table.Seats) == 0) { table.Rules = -1; table.Players = 0; }
            if (reply) output.Add(Delivery.To(guid, Wire(52, Int(index))));
            if (rival != null) output.Add(Delivery.To(rival, Wire(59, "", Int(index))));
        }

        // -------------------------------------------------------------- Bowling
        // Panel replies are actorGuid#laneId#EntryData<BowlingPanelData>.
        // Request/reply variants go to the actor; OneWay variants go to every
        // other announced peer, because inactive spectator lanes cache
        // 74/76/77/78 and request Sync71 (0x5da760, 0x5d98b0, 0x5dabe0,
        // 0x5db460).

        private void BowlingJoin(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 3);
            if (args[1] != caller.PlatformId) throw new Rejected("bowling_platform_id_not_owned");
            int index = TableIndex(args[2], lanes.Length);
            BowlingLane lane = lanes[index];
            if (Seat(lane.Seats, caller.Guid) >= 0) throw new Rejected("minigame_already_seated");
            RequireNotSeated(caller.Guid);
            int seat = Seat(lane.Seats, null);
            if (lane.State >= LaneReady || seat < 0)
            {
                // Get_InitializeGame 0x547a10 Playing branch: busy menu, imIn=false.
                output.Add(Delivery.To(caller.Guid, Wire(64, caller.Guid, Int(index), Panel(lane, LanePlaying))));
                return;
            }
            lane.Seats[seat] = caller;
            lane.Ready[seat] = false;
            // Ready66/74 is only applied over an Awaiting panel, so a joined
            // lane is always reported as Awaiting.
            lane.State = LaneAwaiting;
            output.Add(Delivery.To(caller.Guid, Wire(64, caller.Guid, Int(index), Panel(lane, -1))));
            output.Add(Delivery.Others(caller.Guid, Wire(72, caller.Guid, Int(index), Panel(lane, -1))));
        }

        private void BowlingReady(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 2);
            int index = TableIndex(args[1], lanes.Length);
            BowlingLane lane = lanes[index];
            int seat = RequireSeat(lane.Seats, caller.Guid);
            if (lane.State != LaneAwaiting) throw new Rejected("bowling_lane_not_awaiting");
            lane.Ready[seat] = true;
            bool all = true;
            for (int i = 0; i < BowlingSeats; ++i) if (lane.Seats[i] != null && !lane.Ready[i]) all = false;
            if (all)
            {
                // Ready3 makes every client run Get_StartGame 0x548740, which
                // stands the turnIndex player; start with the first seat.
                lane.State = LaneReady;
                lane.TurnIndex = NextOccupied(lane, -1);
            }
            output.Add(Delivery.To(caller.Guid, Wire(66, caller.Guid, Int(index), Panel(lane, -1))));
            output.Add(Delivery.Others(caller.Guid, Wire(74, caller.Guid, Int(index), Panel(lane, -1))));
            if (all) lane.State = LanePlaying;
        }

        private BowlingLane ActiveLane(Identity caller, string text, out int index, out int seat)
        {
            index = TableIndex(text, lanes.Length);
            BowlingLane lane = lanes[index];
            seat = RequireSeat(lane.Seats, caller.Guid);
            if (lane.State != LanePlaying) throw new Rejected("bowling_no_active_match");
            return lane;
        }

        // BallMoveSendData(10) waits for gotMoveShotFromServer, set by OK.
        private void BowlingShot(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 6);
            ActiveLane(caller, args[1], out int index, out int _);
            for (int i = 2; i < 6; ++i) FiniteFloat(args[i]);
            output.Add(Delivery.To(caller.Guid, Wire(68, Int(index), "OK")));
            output.Add(Delivery.Others(caller.Guid, Wire(76, Int(index), args[2], args[3], args[4], args[5])));
        }

        // Pins: guid#lane#declaredLength#n#{7 tokens per pin}; replay omits
        // guid and declaredLength. Six tokens per pin are BinaryConverter
        // two-UTF16-unit floats (0x4d4260) and are relayed byte-exactly.
        private void BowlingPinsMessage(Identity caller, string[] args, List<Delivery> output)
        {
            if (args.Length < 4) throw new Rejected("minigame_wrong_field_count");
            ActiveLane(caller, args[1], out int index, out int _);
            Integer(args[2]);
            int pins = Integer(args[3]);
            if (pins < 0 || pins > BowlingPins) throw new Rejected("bowling_invalid_pin_count");
            Count(args, 4 + 7 * pins);
            var fields = new List<string> { Int(index), Int(pins) };
            for (int i = 0; i < 7 * pins; ++i)
            {
                string token = args[4 + i];
                if (i % 7 < 6 && token.Length != 2) throw new Rejected("bowling_invalid_pin_float");
                if (token.IndexOf('\0') >= 0 || token.Length > 16) throw new Rejected("bowling_invalid_pin_token");
                fields.Add(token);
            }
            output.Add(Delivery.To(caller.Guid, Wire(69, Int(index), "OK")));
            output.Add(Delivery.Others(caller.Guid, Wire(77, fields.ToArray())));
        }

        // EndShot(14) sends 70 and waits: Get_ChangeTurn 0x5479f0 (via 70 or
        // 78) is what requests ChangeTurn(15). The candidate index is kept
        // only for the panel used by later Sync71 replies.
        private void BowlingTurn(Identity caller, string[] args, List<Delivery> output)
        {
            Count(args, 3);
            BowlingLane lane = ActiveLane(caller, args[1], out int index, out int _);
            int next = Integer(args[2]);
            if (next < 0 || next >= BowlingSeats || lane.Seats[next] == null) throw new Rejected("bowling_invalid_turn_index");
            lane.TurnIndex = next;
            output.Add(Delivery.To(caller.Guid, Wire(70, Int(index))));
            output.Add(Delivery.Others(caller.Guid, Wire(78, Int(index))));
        }

        private void RemoveBowling(string guid, int index, bool reply, List<Delivery> output)
        {
            BowlingLane lane = lanes[index];
            int seat = Seat(lane.Seats, guid);
            if (seat < 0) return;
            // Get_LeaveGame 0x547eb0 diffs old/new panel by slot: no compaction.
            lane.Seats[seat] = null;
            lane.Ready[seat] = false;
            if (NextOccupied(lane, -1) < 0)
            {
                lane.State = LaneFree;
                lane.TurnIndex = 0;
            }
            else if (lane.TurnIndex == seat) lane.TurnIndex = NextOccupied(lane, seat);
            if (reply) output.Add(Delivery.To(guid, Wire(65, guid, Int(index), Panel(lane, -1))));
            output.Add(Delivery.Others(guid, Wire(73, guid, Int(index), Panel(lane, -1))));
        }

        private static int NextOccupied(BowlingLane lane, int after)
        {
            for (int step = 1; step <= BowlingSeats; ++step)
            {
                int i = ((after + step) % BowlingSeats + BowlingSeats) % BowlingSeats;
                if (lane.Seats[i] != null) return i;
            }
            return -1;
        }

        // BowlingPanelData: playerDataPublic[], currentTime, state, turnIndex.
        // currentTime is an absolute CurrentTime.Millis ready deadline
        // (UIBowlingMain.InflatePanel 0x562760/Update 0x563920); 0 disables
        // the countdown because the original deadline length is unrecovered.
        private static string Panel(BowlingLane lane, int stateOverride)
        {
            var fields = new List<string> { Int(BowlingSeats) };
            for (int i = 0; i < BowlingSeats; ++i)
            {
                Identity player = lane.Seats[i];
                fields.Add(player?.DisplayName ?? "");
                fields.Add(player?.PlatformId ?? "");
                fields.Add(player?.Guid ?? "");
                fields.Add(player != null && lane.Ready[i] ? "True" : "False");
                fields.Add("");
            }
            fields.Add("0");
            fields.Add(LaneStates[stateOverride >= 0 ? stateOverride : lane.State]);
            fields.Add(Int(Math.Max(lane.TurnIndex, 0)));
            return Tokens(fields.ToArray());
        }

        // -------------------------------------------------------------- Common

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
            foreach (PoolTable table in pools)
                if (Seat(table.Seats, guid) >= 0) throw new Rejected("minigame_already_seated");
            foreach (BowlingLane lane in lanes)
                if (Seat(lane.Seats, guid) >= 0) throw new Rejected("minigame_already_seated");
        }

        // A null guid finds the first empty seat.
        private static int Seat(Identity[] seats, string guid)
        {
            for (int i = 0; i < seats.Length; ++i)
                if (guid == null ? seats[i] == null : seats[i] != null && seats[i].Guid == guid) return i;
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
            if (value == null || value.Length > 64 ||
                !Single.TryParse(value, NumberStyles.Float, Invariant, out float number) ||
                Single.IsNaN(number) || Single.IsInfinity(number)) throw new Rejected("minigame_invalid_float");
            return number;
        }
    }
}
