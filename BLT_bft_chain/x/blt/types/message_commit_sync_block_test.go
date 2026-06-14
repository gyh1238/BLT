package types

import (
	"testing"

	"leochain/testutil/sample"

	sdkerrors "github.com/cosmos/cosmos-sdk/types/errors"
	"github.com/stretchr/testify/require"
)

func validBody() BltBlockBody {
	return BltBlockBody{
		Global: BltBodyGlobal{
			GlobalRefTimeQ01Ns: 1_000,
			ClusterCount:       1,
			MemberCount:        1,
		},
		ClusterTable: []BltClusterSummary{{ClusterId: 0, HeadId: 100}},
		MemberTable:  []BltMemberRecord{{NodeId: 1, ClusterId: 0}},
	}
}

func TestMsgCommitSyncBlock_ValidateBasic(t *testing.T) {
	tests := []struct {
		name string
		msg  MsgCommitSyncBlock
		err  error
	}{
		{
			name: "invalid address",
			msg:  MsgCommitSyncBlock{Proposer: "invalid_address", Body: validBody()},
			err:  sdkerrors.ErrInvalidAddress,
		},
		{
			name: "ok with valid address and consistent counts",
			msg: MsgCommitSyncBlock{
				Proposer: sample.AccAddress(),
				Body:     validBody(),
			},
		},
		{
			name: "relay path hash wrong length",
			msg: MsgCommitSyncBlock{
				Proposer:      sample.AccAddress(),
				Body:          validBody(),
				RelayPathHash: []byte{0x01, 0x02, 0x03},
			},
			err: sdkerrors.ErrInvalidRequest,
		},
		{
			name: "epoch_id exceeds u8 range",
			msg: MsgCommitSyncBlock{
				Proposer: sample.AccAddress(),
				Body:     validBody(),
				EpochId:  256,
			},
			err: sdkerrors.ErrInvalidRequest,
		},
		{
			name: "cluster_count mismatch",
			msg: func() MsgCommitSyncBlock {
				b := validBody()
				b.Global.ClusterCount = 2
				return MsgCommitSyncBlock{Proposer: sample.AccAddress(), Body: b}
			}(),
			err: sdkerrors.ErrInvalidRequest,
		},
		{
			name: "member_count mismatch",
			msg: func() MsgCommitSyncBlock {
				b := validBody()
				b.Global.MemberCount = 5
				return MsgCommitSyncBlock{Proposer: sample.AccAddress(), Body: b}
			}(),
			err: sdkerrors.ErrInvalidRequest,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.msg.ValidateBasic()
			if tt.err != nil {
				require.ErrorIs(t, err, tt.err)
				return
			}
			require.NoError(t, err)
		})
	}
}
