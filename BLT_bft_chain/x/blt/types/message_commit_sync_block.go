package types

import (
	errorsmod "cosmossdk.io/errors"
	sdk "github.com/cosmos/cosmos-sdk/types"
	sdkerrors "github.com/cosmos/cosmos-sdk/types/errors"
)

var _ sdk.Msg = &MsgCommitSyncBlock{}

func NewMsgCommitSyncBlock(proposer string, body BltBlockBody, relayPathHash []byte, epochId uint32) *MsgCommitSyncBlock {
	return &MsgCommitSyncBlock{
		Proposer:      proposer,
		Body:          body,
		RelayPathHash: relayPathHash,
		EpochId:       epochId,
	}
}

func (msg *MsgCommitSyncBlock) ValidateBasic() error {
	if _, err := sdk.AccAddressFromBech32(msg.Proposer); err != nil {
		return errorsmod.Wrapf(sdkerrors.ErrInvalidAddress, "invalid proposer address (%s)", err)
	}
	if len(msg.RelayPathHash) != 0 && len(msg.RelayPathHash) != 32 {
		return errorsmod.Wrapf(sdkerrors.ErrInvalidRequest, "relay_path_hash must be 32 bytes (got %d)", len(msg.RelayPathHash))
	}
	if msg.EpochId > 255 {
		return errorsmod.Wrapf(sdkerrors.ErrInvalidRequest, "epoch_id %d exceeds u8 range", msg.EpochId)
	}
	if msg.Body.Global.ClusterCount != uint32(len(msg.Body.ClusterTable)) {
		return errorsmod.Wrapf(sdkerrors.ErrInvalidRequest,
			"cluster_count %d does not match cluster_table length %d",
			msg.Body.Global.ClusterCount, len(msg.Body.ClusterTable))
	}
	if msg.Body.Global.MemberCount != uint32(len(msg.Body.MemberTable)) {
		return errorsmod.Wrapf(sdkerrors.ErrInvalidRequest,
			"member_count %d does not match member_table length %d",
			msg.Body.Global.MemberCount, len(msg.Body.MemberTable))
	}
	return nil
}
