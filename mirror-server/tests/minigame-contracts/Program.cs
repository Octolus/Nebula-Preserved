using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using NebulaPreservation;

internal static class Program
{
    private static int passed;
    private static readonly string A = new string('a', 32), B = new string('b', 32), C = new string('c', 32);
    private static readonly Dictionary<string, NebulaMinigameState.Identity> People =
        new Dictionary<string, NebulaMinigameState.Identity>
        {
            [A] = new NebulaMinigameState.Identity(A, "Alice", "ps-a"),
            [B] = new NebulaMinigameState.Identity(B, "Bob", "ps-b"),
            [C] = new NebulaMinigameState.Identity(C, "Carol", "ps-c"),
        };

    private static void Check(bool condition, string name)
    {
        if (!condition) throw new Exception("Minigame contract failed: " + name);
        passed++;
    }

    private static NebulaMinigameState New(int board = 0, int darts = 0, int pool = 0, int bowling = 0) =>
        new NebulaMinigameState(board, darts, pool, bowling, guid => People.TryGetValue(guid, out var p) ? p : null);

    private static IReadOnlyList<NebulaMinigameState.Delivery> Run(NebulaMinigameState state, string guid, int opcode,
        params string[] rest) => state.Handle(guid, opcode, new[] { guid }.Concat(rest).ToArray());

    private static string To(IReadOnlyList<NebulaMinigameState.Delivery> output, string guid) =>
        output.Where(d => d.TargetGuid == guid).Select(d => d.Payload).FirstOrDefault();

    private static string Others(IReadOnlyList<NebulaMinigameState.Delivery> output) =>
        output.Where(d => d.TargetGuid == null).Select(d => d.Payload).SingleOrDefault();

    private static string Rejects(Action action)
    {
        try { action(); }
        catch (NebulaMinigameState.Rejected error) { return error.Code; }
        return null;
    }

    private static string Tokens(params string[] fields)
    {
        var text = new StringBuilder();
        foreach (string field in fields) text.Append((char)(field.Length + 0x24)).Append(field);
        return text.ToString();
    }

    private static List<string> Decode(string text)
    {
        var fields = new List<string>();
        for (int cursor = 0; cursor < text.Length;)
        {
            int length = text[cursor++] - 0x24;
            fields.Add(text.Substring(cursor, length));
            cursor += length;
        }
        return fields;
    }

    private static string Move(int ox, int oy, int x, int y) =>
        Tokens(ox.ToString(), oy.ToString(), x.ToString(), y.ToString());

    private static string BoardState(IReadOnlyList<NebulaMinigameState.Delivery> output, string actor) =>
        To(output, actor).Split('#')[3];

    private static NebulaMinigameState BoardMatch(int rules)
    {
        var state = New(board: 2);
        Run(state, A, 32, "ps-a", "1");
        Run(state, B, 32, "ps-b", "1");
        Run(state, A, 33, "1", rules.ToString());
        var start = Run(state, B, 34, "1");
        Check(To(start, B) == "34#1" && To(start, A) == "41#1", "board start accepted from either seat");
        return state;
    }

    private static string Snapshot(NebulaMinigameState state, int table) =>
        To(Run(state, A, 37), A).Split('#')[2 + table];

    private static void Board()
    {
        var state = New(board: 2);
        var join = Run(state, A, 32, "ps-a", "1");
        Check(To(join, A).StartsWith("32#1#0#") && Others(join).StartsWith("39#1##"), "board join reply and oneway");
        Check(Rejects(() => Run(state, A, 33, "1", "4")) == "board_invalid_rules", "board rejects undefined rules");
        Run(state, B, 32, "ps-b", "1");
        Check(Rejects(() => Run(state, B, 33, "1", "2")) == "minigame_requires_first_seat", "only owner selects rules");
        var select = Run(state, A, 33, "1", "2");
        Check(To(select, A) == "33#1##Chess" && To(select, B) == "40#1##Chess", "chess selectable");

        var ttt = BoardMatch(1);
        var first = Run(ttt, A, 35, "1", Move(0, 0, 0, 0));
        Check(To(first, A) == "35#1##P2Turn#0" && To(first, B) == "43#1##P2Turn#0#" + Move(0, 0, 0, 0),
            "tictactoe actor result and rival replay");
        Check(Rejects(() => Run(ttt, A, 35, "1", Move(0, 0, 1, 1))) == "board_move_out_of_turn", "turn enforced");
        Run(ttt, B, 35, "1", Move(0, 0, 1, 0));
        Run(ttt, A, 35, "1", Move(0, 0, 0, 1));
        Run(ttt, B, 35, "1", Move(0, 0, 1, 1));
        Check(BoardState(Run(ttt, A, 35, "1", Move(0, 0, 0, 2)), A) == "P1Wins", "tictactoe row wins");
        Check(Snapshot(ttt, 0) == "0" && Snapshot(ttt, 1) == "1xxxoo0000", "tictactoe snapshot");

        // Fool's mate: Black mates on move two.
        var chess = BoardMatch(2);
        Check(Snapshot(chess, 1) == "2rnbqkbnrpppppppp00000000000000000000000000000000PPPPPPPPRNBQKBNR", "chess snapshot");
        Check(BoardState(Run(chess, A, 35, "1", Move(1, 5, 2, 5)), A) == "P2Turn", "chess white move");
        Run(chess, B, 35, "1", Move(6, 4, 4, 4));
        Run(chess, A, 35, "1", Move(1, 6, 3, 6));
        var mate = Run(chess, B, 35, "1", Move(7, 3, 3, 7));
        Check(BoardState(mate, B) == "P2Wins" && To(mate, A).StartsWith("43#1##P2Wins#1#"), "chess checkmate reported");
        Check(Rejects(() => Run(chess, A, 35, "1", Move(1, 0, 2, 0))) == "board_no_active_match", "finished game closed");

        // Castling, en passant and promotion bookkeeping.
        var rules = BoardMatch(2);
        string[] script = {
            "1,4,3,4", "6,0,5,0", "0,6,2,5", "5,0,4,0", "0,5,3,2", "4,0,3,0", "1,1,3,1", "3,0,2,1",
        };
        int mover = 0;
        foreach (string step in script)
        {
            int[] m = step.Split(',').Select(int.Parse).ToArray();
            Run(rules, mover == 0 ? A : B, 35, "1", Move(m[0], m[1], m[2], m[3]));
            mover = 1 - mover;
        }
        string text = Snapshot(rules, 1).Substring(1);
        Check(text[1 * 8 + 1] == '0' && text[3 * 8 + 1] == '0' && text[2 * 8 + 1] == 'P', "en passant removes the passed pawn");
        Run(rules, A, 35, "1", Move(0, 4, 0, 6));
        text = Snapshot(rules, 1).Substring(1);
        Check(text[6] == 'k' && text[5] == 'r' && text[7] == '0', "short castling moves the rook");

        var promo = BoardMatch(2);
        string[] race = { "1,0,3,0", "6,1,4,1", "3,0,4,1", "6,7,5,7", "4,1,5,1", "5,7,4,7", "5,1,6,1", "4,7,3,7", "6,1,7,2" };
        mover = 0;
        foreach (string step in race)
        {
            int[] m = step.Split(',').Select(int.Parse).ToArray();
            Run(promo, mover == 0 ? A : B, 35, "1", Move(m[0], m[1], m[2], m[3]));
            mover = 1 - mover;
        }
        Check(Snapshot(promo, 1)[1 + 7 * 8 + 2] == 'q', "pawn promotes to white queen");

        // Draughts capture removes the jumped piece and passes the turn.
        var draughts = BoardMatch(3);
        Check(Snapshot(draughts, 1) == "3R0R0R0R0" + "0R0R0R0R" + "R0R0R0R0" + new string('0', 16) + "0r0r0r0r" + "r0r0r0r0" + "0r0r0r0r", "draughts snapshot");
        Run(draughts, A, 35, "1", Move(2, 2, 3, 3));
        Run(draughts, B, 35, "1", Move(5, 5, 4, 4));
        Check(Rejects(() => Run(draughts, A, 35, "1", Move(3, 3, 4, 3))) == "board_illegal_move", "draughts geometry");
        var capture = Run(draughts, A, 35, "1", Move(3, 3, 5, 5));
        string board = Snapshot(draughts, 1).Substring(1);
        Check(BoardState(capture, A) == "P2Turn" && board[4 * 8 + 4] == '0' && board[5 * 8 + 5] == 'R',
            "draughts capture applied");

        var leave = Run(draughts, B, 36, "1");
        Check(To(leave, B) == "36#" + B + "#1" && To(leave, A) == "42#" + B + "#1", "board leave notifies rival");
    }

    private static void Darts()
    {
        var state = New(darts: 3);
        Run(state, A, 80, "2");
        Check(Rejects(() => Run(state, A, 84, "2")) == "darts_select_rules_first", "darts start needs rules");
        Run(state, A, 82, "2", "1", "2");
        var join = Run(state, B, 80, "2");
        Check(To(join, B).StartsWith("80##2#Awaiting#"), "darts rival awaiting");
        Check(Rejects(() => Run(state, A, 85, "2", Tokens("0", "0", "1", "0", "0"))) == "darts_no_active_match",
            "darts shot needs started match");
        var start = Run(state, B, 84, "2");
        List<string> block = To(start, B).Split('#').ToList();
        Check(block[0] == "84" && block[1] == "2" && block[3] == "2" && block.Count == 6, "darts start table block");
        Check(Decode(block[2]).SequenceEqual(new[] { "Game501", "StartGame", "0", "2", "True" }), "darts active table data");
        Check(To(start, A).StartsWith("90#2#"), "darts start oneway to rival");
        string shot = Tokens("0.125", "-0.5", "0.75", "0.01", "-0.02");
        var move = Run(state, A, 85, "2", shot);
        Check(To(move, A) == "85##2#" + shot && To(move, B) == "91##2#" + shot, "darts shot echoed and relayed");
        Check(Rejects(() => Run(state, A, 85, "2", Tokens("NaN", "0", "0", "0", "0"))) == "minigame_invalid_float",
            "darts rejects non-finite shot");
        Check(To(Run(state, C, 80, "2"), C).StartsWith("80##2#Full#"), "darts busy join replies");
        var leave = Run(state, B, 81, "2");
        Check(To(leave, B) == "81#2#Awaiting" && To(leave, A).StartsWith("88#" + B + "#2#Awaiting"), "darts leave");
    }

    private static void Pool()
    {
        var state = New(pool: 9);
        Check(To(Run(state, A, 51, "4"), A) == "51##4#Free##0", "pool owner free");
        Check(To(Run(state, B, 51, "4"), B) == "51##4#Full##0", "pool busy until rules chosen");
        Check(To(Run(state, A, 53, "4", "1", "2"), A) == "53##4#2", "pool select reply carries player count");
        Check(Rejects(() => Run(state, A, 53, "4", "0", "2")) == "pool_invalid_rules_or_player_count", "pool practice is solo");
        Check(To(Run(state, B, 51, "4"), B) == "51##4#Awaiting#Alice#1", "pool rival sees owner and rules");
        var start = Run(state, B, 54, "4", "2");
        Check(To(start, B) == "54#4#playerTwo#Alice" && To(start, A) == "60#4#playerOne#Bob", "pool start roles");
        var shot = Run(state, A, 55, "4", "0.5", "-1.25", "0", "0.1", "12.5");
        Check(To(shot, A) == "55#4#OK" && To(shot, B) == "61#4#0.5#-1.25#0#0.1#12.5", "pool shot ack and replay");
        var balls = Run(state, A, 56, "4", "8", "2", "0.1", "0.2", "0.3", "0.4", "0", "1", "3", "5");
        Check(To(balls, A) == "56#4#OK" && To(balls, B) == "62#4#2#0.1#0.2#0.3#0.4#0#1#3#5", "pool ball replay drops guid and M");
        Check(Rejects(() => Run(state, A, 56, "4", "8", "2", "0.1")) == "minigame_wrong_field_count", "pool ball layout");
        var foul = Run(state, B, 57, "4", "0.25", "-0.75");
        Check(To(foul, B) == "57#4#OK" && To(foul, A) == "63#4#0.25#-0.75", "pool foul ack and replay");
        var leave = Run(state, B, 52, "4");
        Check(To(leave, B) == "52#4" && To(leave, A) == "59##4", "pool leave and rival gone");

        var solo = New(pool: 1);
        Run(solo, C, 51, "0");
        Run(solo, C, 53, "0", "0", "1");
        Check(To(Run(solo, C, 54, "0", "1"), C) == "54#0#playerOne", "pool solo start");
        var solosShot = Run(solo, C, 55, "0", "1", "1", "1", "1", "1");
        Check(solosShot.Count == 1 && To(solosShot, C) == "55#0#OK", "pool solo shot acknowledged only");
    }

    private static List<string> Panel(string payload)
    {
        string[] fields = payload.Split('#');
        return Decode(fields[3]);
    }

    private static void Bowling()
    {
        var state = New(bowling: 12);
        Check(Rejects(() => Run(state, A, 64, "ps-b", "3")) == "bowling_platform_id_not_owned", "bowling join platform id");
        var join = Run(state, A, 64, "ps-a", "3");
        List<string> panel = Panel(To(join, A));
        Check(To(join, A).StartsWith("64#" + A + "#3#") && Others(join).StartsWith("72#" + A + "#3#"), "bowling join routing");
        Check(panel.Count == 1 + 4 * 5 + 3 && panel[0] == "4" && panel[1] == "Alice" && panel[2] == "ps-a" &&
            panel[3] == A && panel[4] == "False" && panel[6] == "" && panel[21] == "0" && panel[22] == "Awaiting",
            "bowling panel entrydata");
        Run(state, B, 64, "ps-b", "3");
        var ready = Run(state, A, 66, "3");
        Check(Panel(To(ready, A))[22] == "Awaiting" && Others(ready).StartsWith("74#" + A + "#3#"), "bowling partial ready");
        Check(Rejects(() => Run(state, A, 68, "3", "0", "0", "1", "0")) == "bowling_no_active_match", "bowling shot before start");
        var all = Run(state, B, 66, "3");
        Check(Panel(To(all, B))[22] == "Ready" && Panel(To(all, B))[23] == "0", "bowling all ready starts at seat0");
        Check(Panel(To(Run(state, C, 64, "ps-c", "3"), C))[22] == "Playing", "bowling busy lane");
        var shot = Run(state, A, 68, "3", "0.1", "-2", "0.75", "0");
        Check(To(shot, A) == "68#3#OK" && Others(shot) == "76#3#0.1#-2#0.75#0", "bowling shot ack and replay");
        string f = "ሴ䌡";
        var pins = Run(state, A, 69, "3", "9", "1", f, f, f, f, f, f, "0");
        Check(To(pins, A) == "69#3#OK" && Others(pins) == "77#3#1#" + string.Join("#", f, f, f, f, f, f, "0"),
            "bowling pins replay keeps BinaryConverter tokens");
        Check(Rejects(() => Run(state, A, 69, "3", "9", "1", "1.0", f, f, f, f, f, "0")) == "bowling_invalid_pin_float",
            "bowling pin float width");
        var turn = Run(state, A, 70, "3", "1");
        Check(To(turn, A) == "70#3" && Others(turn) == "78#3", "bowling turn ack and oneway");
        var sync = Run(state, C, 71, "3");
        Check(To(sync, C).StartsWith("71#" + C + "#3#") && Panel(To(sync, C))[23] == "1", "bowling sync panel");
        var leave = Run(state, B, 65, "ps-b", "3");
        List<string> after = Panel(To(leave, B));
        Check(Others(leave).StartsWith("73#" + B + "#3#") && after[6] == "" && after[1] == "Alice" && after[23] == "0",
            "bowling leave keeps slots and moves turn");
        var gone = state.Disconnect(A);
        Check(Panel(Others(gone))[22] == "Free", "bowling lane freed on disconnect");
    }

    private static void Common()
    {
        var state = New(board: 1, darts: 1, pool: 1, bowling: 1);
        int[] claimed = Enumerable.Range(0, 100).Where(state.Handles).ToArray();
        Check(string.Join(",", claimed) == "32,33,34,35,36,37,51,52,53,54,55,56,57,64,65,66,68,69,70,71,80,81,82,84,85,86",
            "claimed opcodes are exactly the client senders");
        Run(state, A, 51, "0");
        Check(Rejects(() => Run(state, A, 64, "ps-a", "0")) == "minigame_already_seated", "one seat across games");
        Check(Rejects(() => Run(state, A, 52, "1")) == "minigame_table_not_in_scene", "table count bound");
        Check(Rejects(() => state.Handle(A, 51, new[] { B, "0" })) == "minigame_session_not_owned", "session binding");
        var legacy = new NebulaMinigameState(0, 0, guid => null);
        Check(legacy.PoolTableCount == 0 && legacy.BowlingLaneCount == 0, "legacy constructor disables pool and bowling");
    }

    private static int Main()
    {
        Board();
        Darts();
        Pool();
        Bowling();
        Common();
        Console.WriteLine("Minigame contracts passed: " + passed);
        return 0;
    }
}
