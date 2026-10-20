package types

import (
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"sort"
)

// Merkle commitment over the member table.
//
// The full-record policy puts one BltMemberRecord in every block so that each
// satellite's report stays traceable. At N = 8,192 that table is 133.6 kB of a
// 137 kB block, which is what forces the checkpoint policy the paper describes.
//
// Committing a root instead keeps the traceability and makes it cheaper to
// check. A member proves its own record against a root that consensus finalized,
// using a sibling path it can verify against a block header, rather than by
// holding every other satellite's records. Measured on this schema at 8,192
// members: 137,078 B carrying the table, 380 B carrying the root, 441 B for one
// member's inclusion proof -- a 360.7x reduction on the block.
//
// tools/sizemodel predicts 428 B for that proof rather than 441. The gap is the
// leaf encoding, not an error in either: the model sizes a protobuf-encoded
// leaf while MemberLeaf below is a fixed-width 25-byte canonical form. Quote 441
// as the measurement and 428 only as the model's own output.
//
// Leaves are sorted by node_id before hashing so the root is a function of the
// set, not of the order a proposer happened to serialise it in -- two honest
// proposers with the same measurements must produce the same root. Duplicate
// node_ids are rejected rather than silently folded, since a duplicate would let
// one satellite occupy two leaves.

var (
	// ErrDuplicateMemberNode is returned when the member table names a node
	// twice; the root would otherwise depend on which copy survived.
	ErrDuplicateMemberNode = errors.New("member_table contains a duplicate node_id")

	// ErrProofOutOfRange is returned when an inclusion proof names a leaf index
	// outside the tree it claims to be from.
	ErrProofOutOfRange = errors.New("merkle proof leaf index is outside the tree")
)

// Domain separation: a leaf and an interior node must never hash identically,
// or a proof could present an interior node as a leaf.
const (
	leafPrefix     byte = 0x00
	internalPrefix byte = 0x01
)

// MemberLeaf is the canonical encoding of one member record for hashing.
// Fixed width and explicit byte order, so the digest does not depend on
// protobuf's varint choices or on field ordering.
func MemberLeaf(r BltMemberRecord) []byte {
	b := make([]byte, 0, 1+4+4+4+4+4+4)
	b = append(b, leafPrefix)
	b = binary.BigEndian.AppendUint32(b, r.NodeId)
	b = binary.BigEndian.AppendUint32(b, r.ClusterId)
	b = binary.BigEndian.AppendUint32(b, uint32(r.OffsetToHeadQ01Ns))
	b = binary.BigEndian.AppendUint32(b, r.RespProbQ255)
	b = binary.BigEndian.AppendUint32(b, r.TimeAccQ01Ns)
	b = binary.BigEndian.AppendUint32(b, r.Flags)
	return b
}

func leafHash(r BltMemberRecord) [32]byte { return sha256.Sum256(MemberLeaf(r)) }

func internalHash(l, r [32]byte) [32]byte {
	b := make([]byte, 0, 1+32+32)
	b = append(b, internalPrefix)
	b = append(b, l[:]...)
	b = append(b, r[:]...)
	return sha256.Sum256(b)
}

// sortedLeaves returns the per-record hashes in node_id order.
func sortedLeaves(records []BltMemberRecord) ([][32]byte, error) {
	ordered := make([]BltMemberRecord, len(records))
	copy(ordered, records)
	sort.Slice(ordered, func(i, j int) bool { return ordered[i].NodeId < ordered[j].NodeId })

	leaves := make([][32]byte, len(ordered))
	for i, r := range ordered {
		if i > 0 && ordered[i-1].NodeId == r.NodeId {
			return nil, ErrDuplicateMemberNode
		}
		leaves[i] = leafHash(r)
	}
	return leaves, nil
}

// MemberRoot returns the Merkle root over a member table. An empty table has an
// empty root rather than the hash of nothing, so "no members" and "members whose
// digest happens to be zero" stay distinguishable on the wire.
func MemberRoot(records []BltMemberRecord) ([]byte, error) {
	leaves, err := sortedLeaves(records)
	if err != nil {
		return nil, err
	}
	if len(leaves) == 0 {
		return nil, nil
	}
	level := leaves
	for len(level) > 1 {
		next := make([][32]byte, 0, (len(level)+1)/2)
		for i := 0; i < len(level); i += 2 {
			if i+1 == len(level) {
				// Odd node promotes unchanged. Cheaper than duplicating it, and
				// duplication is what allows the classic second-preimage trick
				// where a tree of n leaves collides with one of n-1.
				next = append(next, level[i])
				continue
			}
			next = append(next, internalHash(level[i], level[i+1]))
		}
		level = next
	}
	root := level[0]
	return root[:], nil
}

// MemberProof is the sibling path proving one leaf is in the committed set.
type MemberProof struct {
	LeafIndex uint32   // position in node_id order
	NumLeaves uint32   // tree size, needed to replay the odd-node promotion
	Siblings  [][]byte // bottom-up, 32 bytes each
}

// ProveMember builds the inclusion proof for one node_id.
func ProveMember(records []BltMemberRecord, nodeID uint32) (BltMemberRecord, MemberProof, error) {
	ordered := make([]BltMemberRecord, len(records))
	copy(ordered, records)
	sort.Slice(ordered, func(i, j int) bool { return ordered[i].NodeId < ordered[j].NodeId })

	idx := -1
	for i, r := range ordered {
		if i > 0 && ordered[i-1].NodeId == r.NodeId {
			return BltMemberRecord{}, MemberProof{}, ErrDuplicateMemberNode
		}
		if r.NodeId == nodeID {
			idx = i
		}
	}
	if idx < 0 {
		return BltMemberRecord{}, MemberProof{}, ErrProofOutOfRange
	}

	level := make([][32]byte, len(ordered))
	for i, r := range ordered {
		level[i] = leafHash(r)
	}

	proof := MemberProof{LeafIndex: uint32(idx), NumLeaves: uint32(len(ordered))}
	pos := idx
	for len(level) > 1 {
		next := make([][32]byte, 0, (len(level)+1)/2)
		for i := 0; i < len(level); i += 2 {
			if i+1 == len(level) {
				next = append(next, level[i])
				continue
			}
			if i == pos || i+1 == pos {
				sib := level[i+1]
				if pos == i+1 {
					sib = level[i]
				}
				s := make([]byte, 32)
				copy(s, sib[:])
				proof.Siblings = append(proof.Siblings, s)
			}
			next = append(next, internalHash(level[i], level[i+1]))
		}
		pos /= 2
		level = next
	}
	return ordered[idx], proof, nil
}

// VerifyMember checks a record against a committed root. This is what a member
// satellite runs: it needs the root (from a block header), its own record, and
// the sibling path -- not the rest of the table.
func VerifyMember(root []byte, record BltMemberRecord, proof MemberProof) bool {
	if len(root) != 32 || proof.NumLeaves == 0 || proof.LeafIndex >= proof.NumLeaves {
		return false
	}
	h := leafHash(record)
	pos := proof.LeafIndex
	width := proof.NumLeaves
	si := 0
	for width > 1 {
		isOddTail := pos == width-1 && width%2 == 1
		if !isOddTail {
			if si >= len(proof.Siblings) {
				return false
			}
			var sib [32]byte
			copy(sib[:], proof.Siblings[si])
			si++
			if pos%2 == 0 {
				h = internalHash(h, sib)
			} else {
				h = internalHash(sib, h)
			}
		}
		pos /= 2
		width = (width + 1) / 2
	}
	if si != len(proof.Siblings) {
		return false
	}
	for i := range h {
		if h[i] != root[i] {
			return false
		}
	}
	return true
}
