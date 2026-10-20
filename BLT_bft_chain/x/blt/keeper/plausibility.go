package keeper

import (
	"math"

	errorsmod "cosmossdk.io/errors"
	sdk "github.com/cosmos/cosmos-sdk/types"

	"leochain/x/blt/types"
)

// ----------------------------------------------------------------------------
// Ledger-dependent (stateful) admission rules
// ----------------------------------------------------------------------------
//
// Every check in msg_server_commit_sync_block.go up to the intra-message
// plausibility test can be decided by looking at the message alone. A single
// authenticated snapshot signed by one trusted head would satisfy all of them
// equally well, which is precisely the question "what does the chain
// add?".
//
// The rules below cannot be decided from the message. Each one compares the
// proposal against something the network has *already agreed on*:
//
//   R1 (round order):  the height and epoch id of the previously committed epoch.
//   R2 (monotonicity): the reference time the network previously accepted.
//   R3 (BFT anchor):   the consensus block time, i.e. the stake-weighted
//                       median of validator-reported clocks. A coalition
//                       holding less than 1/3 of voting power cannot move it,
//                       so a fabricated global reference time is a claim the
//                       network can *refuse*, not merely one it can log.
//
// R3 is the part that a signed snapshot fundamentally cannot reproduce: it
// checks the proposer's assertion against an independent time estimate that no
// single participant produces. R1 and R2 are what make the ledger load-bearing
// rather than decorative: remove the stored history and they cannot be
// evaluated at all.

// q01PerNano converts nanoseconds to the q01ns (0.1 ns) unit used on the wire.
const q01PerNano = 10

// refSkewToleranceEpochs sets the BFT-time anchor window as a multiple of the
// configured epoch length. The proposer necessarily samples the constellation
// before its block is committed, and CometBFT's own timestamp is itself a
// median with spread, so the window must cover at least one full round trip.
// Two epochs (7 s at the default epoch_length_ms = 3500) is loose enough never
// to reject an honest proposal and tight enough that a fabricated timeline is
// caught within one round instead of accumulating silently.
const refSkewToleranceEpochs = 2

// validateAgainstLedger applies R1-R3. It is separated from the msg server so
// the rules can be unit-tested (and cited in the paper) on their own.
func (k Keeper) validateAgainstLedger(ctx sdk.Context, msg *types.MsgCommitSyncBlock) error {
	params := k.GetParams(ctx)
	claimed := msg.Body.Global.GlobalRefTimeQ01Ns

	// R3: anchor the assertion to consensus time. Evaluated first because it
	// holds for the very first epoch too, when there is no predecessor.
	blockNs, ok := blockRefNs(ctx)
	if !ok {
		return errorsmod.Wrapf(types.ErrRefTimeSkew,
			"block time %s is outside the representable window from the q01ns anchor",
			ctx.BlockTime().UTC())
	}
	// Compare in nanoseconds: claimed is a uint64 the proposer controls, and
	// dividing before the signed conversion keeps a hostile value from wrapping
	// into a plausible-looking difference.
	claimedNs := int64(claimed / q01PerNano)
	tolNs := int64(params.EpochLengthMs) * refSkewToleranceEpochs * 1_000_000
	if skew := claimedNs - blockNs; abs64(skew) > tolNs {
		return errorsmod.Wrapf(types.ErrRefTimeSkew,
			"claimed=%d block=%d skew=%d tolerance=%d (ns from anchor)",
			claimedNs, blockNs, skew, tolNs)
	}

	prev, hasPrev := k.GetLatestEpoch(ctx)
	if !hasPrev {
		return nil
	}

	// R1: one epoch per block, and never a round that has already passed.
	// This is also what stops a replayed MsgCommitSyncBlock: the tx stays valid
	// by signature forever, but the height it targets is consumed.
	if ctx.BlockHeight() <= prev.Height {
		return errorsmod.Wrapf(types.ErrStaleRound,
			"height=%d already has a committed epoch at height=%d", ctx.BlockHeight(), prev.Height)
	}

	// R1b: epoch ids move forward too. The id index (EpochHistoryKey) is keyed by
	// a u8 that wraps every 256 rounds, so a reused id would overwrite the
	// snapshot an earlier round committed under it -- found by chain_scale.sh,
	// where a delegate re-submitting an already committed id was accepted at a new
	// height and replaced that id's record. Only ids 1..128 ahead of the previous
	// one (mod 256) are accepted: gaps and the wrap stay legal, reuse and
	// backward ids do not. The height index was never affected.
	if ahead := (int(msg.EpochId) - int(prev.EpochId) + 256) % 256; ahead == 0 || ahead > 128 {
		return errorsmod.Wrapf(types.ErrEpochIdNotAdvancing,
			"epoch_id=%d previous=%d (height %d)", msg.EpochId, prev.EpochId, prev.Height)
	}

	// R2: the constellation reference must move forward. A rollback would let a
	// Byzantine head replay an old (validly signed) global time to drag the
	// swarm backwards, undetectable to a receiver holding only the latest
	// state, rejected outright once the previous value is consensus state.
	if claimed <= prev.Body.Global.GlobalRefTimeQ01Ns {
		return errorsmod.Wrapf(types.ErrNonMonotonicTime,
			"claimed=%d previous=%d (epoch %d at height %d)",
			claimed, prev.Body.Global.GlobalRefTimeQ01Ns, prev.EpochId, prev.Height)
	}

	return nil
}

// blockRefNs returns the consensus block time relative to the q01ns anchor, in
// nanoseconds. It reports false when the header time falls outside the window
// the encoding can represent, before the anchor, or roughly 29 years after it,
// where the q01ns conversion would overflow uint64/int64. Callers must treat
// that as a rejection rather than clamping, so an unset or nonsensical header
// can never alias onto a plausible reference time.
func blockRefNs(ctx sdk.Context) (int64, bool) {
	t := ctx.BlockTime().UnixNano()
	if t < RefEpochUnixNano {
		return 0, false
	}
	d := t - RefEpochUnixNano
	if d > math.MaxInt64/q01PerNano {
		return 0, false
	}
	return d, true
}
