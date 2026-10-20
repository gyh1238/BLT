using System;
using System.Globalization;
using System.IO;

// Parity harness for BLT_dt/Assets/Scripts/IslLinkModel.cs against blt_isl.py.
// Reads positions.csv (x,y,z,cluster) and heads.csv (one head id per cluster),
// prints "key value" lines that tools/isl_parity.py compares with Python.
static class Parity
{
    static int Main(string[] args)
    {
        var inv = CultureInfo.InvariantCulture;
        var lines = File.ReadAllLines(args[0]);
        int n = lines.Length;
        var pos = new double[3 * n];
        var cluster = new int[n];
        for (int i = 0; i < n; i++)
        {
            var f = lines[i].Split(',');
            pos[3 * i] = double.Parse(f[0], inv);
            pos[3 * i + 1] = double.Parse(f[1], inv);
            pos[3 * i + 2] = double.Parse(f[2], inv);
            cluster[i] = int.Parse(f[3], inv);
        }
        var heads = Array.ConvertAll(File.ReadAllLines(args[1]), s => int.Parse(s, inv));
        var p = new IslLinkParams();
        Console.WriteLine("k " + p.OutageExponent.ToString("R", inv));
        foreach (double d in new[] { 0.0, 1250.0, 2000.0, 2400.0, 2500.0 })
            Console.WriteLine($"pout_{d:F0} " + IslLinkModel.OutageProb(d, p).ToString("R", inv));

        var state = new IslLinkState();
        var g = state.Update(pos, null, n, 0.0, p);
        Console.WriteLine("links " + g.Keys.Length);
        double keySum = 0;
        foreach (long key in g.Keys) keySum += key % 1000003;
        Console.WriteLine("key_checksum " + keySum.ToString("R", inv));

        double hopSum = 0, lossSum = 0; int routed = 0, unroutable = 0, maxDepth = 0;
        var member = new bool[n];
        for (int c = 0; c < heads.Length; c++)
        {
            for (int i = 0; i < n; i++) member[i] = cluster[i] == c;
            var tree = new IslRouteTree(g, heads[c], member, p.routeHopCost);
            var succ = tree.PathSuccess();
            for (int i = 0; i < n; i++)
            {
                if (cluster[i] != c || i == heads[c]) continue;
                if (tree.Depth[i] < 0) { unroutable++; continue; }
                routed++; hopSum += tree.Depth[i]; lossSum += 1.0 - succ[i];
                maxDepth = Math.Max(maxDepth, tree.Depth[i]);
            }
        }
        Console.WriteLine("routed " + routed);
        Console.WriteLine("unroutable " + unroutable);
        Console.WriteLine("hops_mean " + (hopSum / routed).ToString("R", inv));
        Console.WriteLine("hops_max " + maxDepth);
        Console.WriteLine("loss_mean " + (lossSum / routed).ToString("R", inv));

        // Drawn loss over many rounds must match the expectation.
        var rng = new Random(7919);
        var reach = new bool[n];
        for (int i = 0; i < n; i++) member[i] = cluster[i] == 0;
        var t0 = new IslRouteTree(g, heads[0], member, p.routeHopCost);
        var s0 = t0.PathSuccess();
        double expect = 0, got = 0; int cnt = 0;
        for (int i = 0; i < n; i++) if (cluster[i] == 0 && t0.Depth[i] > 0) { expect += s0[i]; cnt++; }
        const int rounds = 2000;
        for (int r = 0; r < rounds; r++)
        {
            t0.Draw(rng, reach);
            for (int i = 0; i < n; i++) if (cluster[i] == 0 && t0.Depth[i] > 0 && reach[i]) got++;
        }
        Console.WriteLine("draw_expected " + (expect / cnt).ToString("R", inv));
        Console.WriteLine("draw_observed " + (got / rounds / cnt).ToString("R", inv));

        // Acquisition: move everything 1 km so no link changes, then test a new pair.
        var pair = new IslLinkState();
        double r0 = IslLinkModel.EarthRadiusKm + 550.0;
        var far = new[] { r0, 0, 0, r0 * Math.Cos(3000 / r0), r0 * Math.Sin(3000 / r0), 0 };
        var near = new[] { r0, 0, 0, r0 * Math.Cos(1000 / r0), r0 * Math.Sin(1000 / r0), 0 };
        int a0 = pair.Update(far, null, 2, 0.0, p).Keys.Length;
        int a1 = pair.Update(near, null, 2, 10.0, p).Keys.Length;
        int a2 = pair.Update(near, null, 2, 10.0 + p.acquisitionSec, p).Keys.Length;
        Console.WriteLine($"acq_far {a0}");
        Console.WriteLine($"acq_new {a1}");
        Console.WriteLine($"acq_after {a2}");
        return 0;
    }
}
