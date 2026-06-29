package keeper

import (
	"fmt"
	"math/rand"
	"strconv"

	sdk "github.com/cosmos/cosmos-sdk/types"

	"leochain/x/blt/types"
)

// ----------------------------------------------------------------------------
// Self-driving demo epoch generation (EndBlocker path)
// ----------------------------------------------------------------------------
//
// In a real deployment a rotating cluster-head proposer submits the per-block
// MsgCommitSyncBlock carrying measured offsets. For the digital-twin demo there
// is no live satellite swarm, so the chain itself synthesizes a plausible
// BLT-SAND sync epoch each block.
//
// Determinism requirement: every validator must derive identical state, so the
// only entropy source is consensus data — here the block height. We seed a PRNG
// with height (the same Knuth multiplicative constant the DT uses for its local
// SAT-ID generation) and use INTEGER-ONLY arithmetic throughout: floating-point
// results can differ in the last ULP across architectures/Go versions, which on
// a multi-validator chain would fork the app hash. All quantities below stay in
// fixed-point integer units (milli-ns, q01ns).
//
// The proposer SAT-ID and the network RMSE — values the DT previously fabricated
// locally — are now produced here and read back by the DT over RPC, so the
// blockchain is the single source of truth. Faulty-node designation and cluster
// assignment are intentionally NOT generated here (identical either side).
//
// buildEpochBody is kept self-contained so an external generator can later
// produce the same body and submit it through MsgCommitSyncBlock instead.

const (
	// satIDBase is the offset applied to a head_id when formatting a display
	// SAT-ID. The DT formats the same way ("SAT-%05d", 40000+head_id), so a
	// head_id in [0,29999] yields SAT-40000..SAT-69999.
	satIDBase = 40000

	// refEpochUnixNano anchors global_ref_time so the q01ns (0.1 ns) value stays
	// well inside uint64 range. 2025-01-01T00:00:00Z.
	refEpochUnixNano int64 = 1735689600_000000000

	// knuth is the multiplicative hashing constant shared with the DT.
	knuth uint64 = 2654435761
)

// Note: the nominal RMSE (milli-ns) and members-per-cluster were previously
// hardcoded here; they are now genesis-configurable module params
// (Params.NominalRmseMilliNs / Params.MembersPerCluster, defaults 6700 / 683).

// GenerateEpoch synthesizes, persists and announces one sync epoch for the
// current block. Safe to call every EndBlock; it is a pure function of the
// block height and the (consensus) block time.
func (k Keeper) GenerateEpoch(ctx sdk.Context) error {
	height := ctx.BlockHeight()
	if height <= 0 {
		return nil
	}
	params := k.GetParams(ctx)
	clusterCount := params.ClusterCount
	if clusterCount == 0 {
		return nil
	}

	// The cluster heads are stable for the session; only the proposer pointer
	// rotates. Seed them once (or honour a genesis-provided set).
	set := k.GetDelegateSet(ctx)
	if len(set.Delegates) == 0 {
		set = buildDelegateSet(clusterCount)
		if err := k.SetDelegateSet(ctx, set); err != nil {
			return fmt.Errorf("seed delegate set: %w", err)
		}
	}

	// Proposer rotates deterministically across the heads by block height.
	proposerIdx := int(height % int64(len(set.Delegates)))
	proposerHead := set.Delegates[proposerIdx].HeadId

	// Per-block body, seeded purely by height → identical on every validator.
	// Demo tuning (nominal RMSE, members/cluster) comes from genesis params.
	rng := rand.New(rand.NewSource(deriveSeed(height)))
	body := buildEpochBody(rng, set, ctx.BlockTime().UnixNano(), height,
		int64(params.NominalRmseMilliNs), int(params.MembersPerCluster))

	snap := types.BltEpochSnapshot{
		EpochId:       uint32(height),
		Height:        height,
		Proposer:      SatLabel(proposerHead),
		RelayPathHash: deriveRelayHash(rng),
		Body:          body,
	}
	if err := k.SetLatestEpoch(ctx, snap); err != nil {
		return fmt.Errorf("set latest epoch: %w", err)
	}
	// NOTE: epoch history is deliberately not written on the self-gen path to
	// keep state bounded over a long-running demo; the DT builds its own rolling
	// window by polling LatestEpoch. The real MsgCommitSyncBlock path still
	// persists history for externally-submitted epochs.

	rmseMilliNs := networkRmseMilliNs(body.ClusterTable)
	ctx.EventManager().EmitEvent(sdk.NewEvent(
		types.EventTypeBlockCommitted,
		sdk.NewAttribute(types.AttributeKeyEpochID, strconv.FormatUint(uint64(snap.EpochId), 10)),
		sdk.NewAttribute(types.AttributeKeyGlobalRefTimeQ01ns, strconv.FormatUint(body.Global.GlobalRefTimeQ01Ns, 10)),
		sdk.NewAttribute(types.AttributeKeyHeight, strconv.FormatInt(height, 10)),
		sdk.NewAttribute(types.AttributeKeyProposer, snap.Proposer),
		sdk.NewAttribute(types.AttributeKeyClusterCount, strconv.FormatUint(uint64(body.Global.ClusterCount), 10)),
		sdk.NewAttribute(types.AttributeKeyMemberCount, strconv.FormatUint(uint64(body.Global.MemberCount), 10)),
		sdk.NewAttribute(types.AttributeKeyNetworkRmseMilliNs, strconv.FormatInt(rmseMilliNs, 10)),
	))
	return nil
}

// buildDelegateSet assigns each cluster a stable head_id in a disjoint band so
// the 12 SAT-IDs never collide. Deterministic in the cluster index alone.
func buildDelegateSet(clusterCount uint32) types.BltDelegateSet {
	delegates := make([]types.BltDelegate, 0, clusterCount)
	for i := uint32(0); i < clusterCount; i++ {
		r := rand.New(rand.NewSource(int64(i+1) * int64(knuth)))
		headID := i*2400 + uint32(r.Intn(2000)) // disjoint 2400-wide bands
		delegates = append(delegates, types.BltDelegate{
			ClusterId:        i,
			HeadId:           headID,
			ValidatorAddress: "", // self-gen path has no on-chain validator binding
		})
	}
	return types.BltDelegateSet{Delegates: delegates}
}

// buildEpochBody synthesizes the per-block global view and cluster table. The
// member table is left empty on the self-gen path (full-record policy applies
// only to externally-submitted epochs); global.member_count still reports the
// aggregate swarm size for display.
func buildEpochBody(rng *rand.Rand, set types.BltDelegateSet, blockUnixNano, height int64,
	nominalRmseMilliNs int64, membersPerCluster int) types.BltBlockBody {
	clusterCount := uint32(len(set.Delegates))

	// Network RMSE target wobbles slowly in the ~5–8 ns band using two integer
	// triangle waves of incommensurate periods — smooth and non-repeating, with
	// no floating point. The baseline comes from genesis params.
	targetMilliNs := nominalRmseMilliNs +
		triangle(height, 50, 1000) +
		triangle(height, 130, 400)
	targetMilliNs = clampI(targetMilliNs, 3000, 9500)

	clusterTable := make([]types.BltClusterSummary, 0, clusterCount)
	var totalMembers uint32
	for _, d := range set.Delegates {
		jitter := int64(rng.Intn(601) - 300) // ±0.3 ns in milli-ns
		clusterMilliNs := clampI(targetMilliNs+jitter, 1000, 12000)
		q01 := clusterMilliNs / 100                 // ns*10 (0.1 ns units)
		varQ := uint32(q01 * q01)                   // (0.1 ns)^2

		mm := membersPerCluster + rng.Intn(41) - 20 // e.g. 663..703 for 683
		if mm < 1 {
			mm = 1 // guard against a misconfigured (tiny) members_per_cluster
		}
		members := uint32(mm)
		out := uint32(rng.Intn(6)) // a few outliers
		if out > members {
			out = members
		}
		inliers := members - out
		totalMembers += members

		clusterTable = append(clusterTable, types.BltClusterSummary{
			ClusterId:               d.ClusterId,
			HeadId:                  d.HeadId,
			HeadOffsetToGlobalQ01Ns: int32(rng.Intn(201) - 100), // ±10 ns
			MemberCount:             members,
			InlierCount:             inliers,
			MemberOffsetMeanQ01Ns:   int32(rng.Intn(101) - 50), // ±5 ns
			MemberOffsetVarQ01Ns2:   varQ,
		})
	}

	grt := uint64((blockUnixNano - refEpochUnixNano) * 10) // 0.1 ns units
	return types.BltBlockBody{
		Global: types.BltBodyGlobal{
			GlobalRefTimeQ01Ns: grt,
			ClusterCount:       clusterCount,
			MemberCount:        totalMembers,
		},
		ClusterTable: clusterTable,
		MemberTable:  []types.BltMemberRecord{},
	}
}

// networkRmseMilliNs returns the network RMSE in milli-nanoseconds, computed as
// sqrt(mean cluster variance) over the cluster table using integer isqrt.
// Mirrors the reduction the DT performs so the event attribute and the queried
// body agree: rmse_ns = sqrt(meanVar)/10  →  milli_ns = sqrt(meanVar)*100.
func networkRmseMilliNs(rows []types.BltClusterSummary) int64 {
	if len(rows) == 0 {
		return 0
	}
	var sum uint64
	for _, r := range rows {
		sum += uint64(r.MemberOffsetVarQ01Ns2)
	}
	meanVar := sum / uint64(len(rows))
	return int64(isqrt(meanVar)) * 100
}

// SatLabel formats a head_id as the DT-facing SAT-ID. Kept identical to the
// DT's formatting so both sides render the same identifier.
func SatLabel(headID uint32) string {
	return fmt.Sprintf("SAT-%05d", satIDBase+headID)
}

// deriveSeed mixes the block height with Knuth's multiplicative constant. The
// uint64 multiply intentionally wraps; the result is cast to int64 for the PRNG
// source. Pure function of height → all validators agree.
func deriveSeed(height int64) int64 {
	return int64(uint64(height) * knuth)
}

// deriveRelayHash returns a deterministic 32-byte placeholder relay-path hash.
func deriveRelayHash(rng *rand.Rand) []byte {
	b := make([]byte, 32)
	for i := range b {
		b[i] = byte(rng.Intn(256))
	}
	return b
}

// triangle is an integer triangle wave of the given period, ranging in
// [-amp, +amp], evaluated at x. Deterministic, no floating point.
func triangle(x, period, amp int64) int64 {
	if period <= 0 {
		return 0
	}
	p := ((x % period) + period) % period // 0..period-1
	half := period / 2
	if half == 0 {
		return 0
	}
	var t int64
	if p < half {
		t = p
	} else {
		t = period - p
	}
	// t in 0..half → map to -amp..+amp
	return amp*(2*t-half) / half
}

// isqrt is integer floor square root for uint64.
func isqrt(n uint64) uint64 {
	if n == 0 {
		return 0
	}
	x := n
	y := (x + 1) / 2
	for y < x {
		x = y
		y = (x + n/x) / 2
	}
	return x
}

func clampI(v, lo, hi int64) int64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}
