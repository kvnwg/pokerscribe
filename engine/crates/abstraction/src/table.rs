//! Bucket tables on disk.
//!
//! One file per street. Layout, all numbers little-endian:
//!
//! | Bytes | What |
//! | --- | --- |
//! | 8 | The magic text `PSABSTR\n` |
//! | 4 | Format version ([`FORMAT_VERSION`]) |
//! | 4 | Length `H` of the header |
//! | `H` | The header: JSON, see [`Header`]. It holds the settings the table was built with |
//! | `hands * bytes_per_bucket` | The bucket of every canonical hand, in index order |
//! | `buckets * 8` | How many real hands are in each bucket |
//! | `buckets * 4` | Each bucket's average equity at showdown against a random hand |
//! | `buckets * centroid_dim * 4` | Each bucket's centre |
//! | depends on `metric` | The distances between buckets, see [`MetricData`] |
//! | 8 | XXH64 (seed 0) of every byte before this one |
//!
//! A table is read with one read of the whole file. Looking up a bucket is one array read.

use crate::emd::{Line, Matrix, Metric};
use crate::kmeans::KMeansSettings;
use crate::xxh64::{xxh64, Xxh64};
use serde::{Deserialize, Serialize};
use std::io::{self, Read, Write};
use std::path::Path;

pub const MAGIC: &[u8; 8] = b"PSABSTR\n";
/// Changes when the file layout or the meaning of a field changes.
pub const FORMAT_VERSION: u32 = 1;

/// A betting round.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Street {
    Preflop,
    Flop,
    Turn,
    River,
}

impl Street {
    /// Board cards on this street.
    pub const fn board_cards(self) -> usize {
        match self {
            Street::Preflop => 0,
            Street::Flop => 3,
            Street::Turn => 4,
            Street::River => 5,
        }
    }

    pub const fn name(self) -> &'static str {
        match self {
            Street::Preflop => "preflop",
            Street::Flop => "flop",
            Street::Turn => "turn",
            Street::River => "river",
        }
    }

    /// The street with this many board cards.
    pub fn from_board_cards(n: usize) -> Option<Street> {
        match n {
            0 => Some(Street::Preflop),
            3 => Some(Street::Flop),
            4 => Some(Street::Turn),
            5 => Some(Street::River),
            _ => None,
        }
    }

    /// The table's file name inside a directory of tables.
    pub fn file_name(self) -> String {
        format!("{}.abs", self.name())
    }
}

/// What describes a hand before clustering.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Feature {
    /// River: equity against a random hand. One number.
    Equity,
    /// River: opponent cluster hand strength, the equity against each of `clusters` groups
    /// of opponent hole cards.
    Ochs { clusters: u8 },
    /// Flop and turn: the histogram over the next street's buckets (potential-aware).
    NextBuckets,
    /// Turn: the histogram over `bins` equal slices of river equity.
    EquityBins { bins: u16 },
}

/// The settings one street's table is built with.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct StreetSettings {
    /// Buckets asked for. The table can hold fewer if there are fewer distinct hands.
    pub buckets: u32,
    pub feature: Feature,
    pub kmeans: KMeansSettings,
}

/// How the distances between a table's buckets are stored.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum MetricKind {
    /// Nothing stored.
    None,
    /// `buckets * 4` bytes: each bucket's place on a line.
    Line,
    /// `buckets * buckets * 4` bytes of distances, then `buckets * embed_dim * 4` bytes:
    /// each bucket's point for the lower bound.
    Matrix,
}

/// The JSON header of a table file.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Header {
    pub format: u32,
    /// The version of this crate that built the table.
    pub built_by: String,
    pub street: Street,
    /// Ranks in the deck: 13 for the real game.
    pub ranks: u8,
    /// Canonical hands, which is the number of entries.
    pub hands: u64,
    /// Buckets in use.
    pub buckets: u32,
    /// 1 when `buckets` is at most 256, else 2.
    pub bytes_per_bucket: u8,
    pub centroid_dim: u32,
    pub metric: MetricKind,
    pub embed_dim: u32,
    pub seed: u64,
    pub settings: StreetSettings,
    /// What the histograms are over: the checksum of the next street's table, or a note.
    pub built_from: String,
    /// River tables made with OCHS: the opponent group of each class of hole cards, in
    /// [`crate::Preflop`]'s order.
    pub opponent_clusters: Vec<u8>,
    /// Lloyd iterations of the k-means run.
    pub iterations: u32,
    /// Hands the centres were trained on.
    pub trained_on: u64,
    /// Average cost of a real hand at its bucket's centre: squared distance for the river,
    /// earth mover's distance for the flop and turn.
    pub cost: f64,
}

/// Distances between a table's buckets, as stored.
#[derive(Clone, Debug, PartialEq)]
pub enum MetricData {
    None,
    Line { pos: Vec<f32> },
    Matrix { d: Vec<f32>, embed: Vec<f32> },
}

/// One street's bucket table.
#[derive(Clone, Debug)]
pub struct Table {
    pub header: Header,
    /// The buckets, `bytes_per_bucket` bytes each.
    payload: Vec<u8>,
    /// Real hands in each bucket.
    pub sizes: Vec<u64>,
    /// Average showdown equity of each bucket. Buckets are numbered by it, weakest first.
    pub equity: Vec<f32>,
    /// `buckets * centroid_dim` numbers.
    pub centroids: Vec<f32>,
    pub metric: MetricData,
}

fn bad(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.into())
}

fn floats(bytes: &[u8]) -> Vec<f32> {
    bytes
        .chunks_exact(4)
        .map(|b| f32::from_le_bytes(b.try_into().unwrap()))
        .collect()
}

impl Table {
    /// Makes a table from the bucket of every canonical hand. Fills in the header's
    /// `format`, `built_by`, `hands`, `buckets`, `bytes_per_bucket`, `centroid_dim`,
    /// `metric` and `embed_dim`.
    pub fn new(
        mut header: Header,
        buckets: &[u16],
        sizes: Vec<u64>,
        equity: Vec<f32>,
        centroids: Vec<f32>,
        metric: MetricData,
    ) -> Table {
        let k = sizes.len();
        assert!(k >= 1 && equity.len() == k && centroids.len() % k == 0);
        assert!(buckets.iter().all(|&b| (b as usize) < k), "bucket number out of range");
        let wide = k > 256;
        let payload: Vec<u8> = if wide {
            buckets.iter().flat_map(|b| b.to_le_bytes()).collect()
        } else {
            buckets.iter().map(|&b| b as u8).collect()
        };
        header.format = FORMAT_VERSION;
        header.built_by = format!("abstraction {}", env!("CARGO_PKG_VERSION"));
        header.hands = buckets.len() as u64;
        header.buckets = k as u32;
        header.bytes_per_bucket = if wide { 2 } else { 1 };
        header.centroid_dim = (centroids.len() / k) as u32;
        (header.metric, header.embed_dim) = match &metric {
            MetricData::None => (MetricKind::None, 0),
            MetricData::Line { pos } => {
                assert_eq!(pos.len(), k);
                (MetricKind::Line, 0)
            }
            MetricData::Matrix { d, embed } => {
                assert_eq!(d.len(), k * k);
                assert_eq!(embed.len() % k, 0);
                (MetricKind::Matrix, (embed.len() / k) as u32)
            }
        };
        Table {
            header,
            payload,
            sizes,
            equity,
            centroids,
            metric,
        }
    }

    /// Canonical hands in the table.
    pub fn len(&self) -> u64 {
        self.header.hands
    }

    pub fn is_empty(&self) -> bool {
        self.header.hands == 0
    }

    /// Buckets in use.
    pub fn buckets(&self) -> usize {
        self.header.buckets as usize
    }

    /// The bucket of the canonical hand with this index.
    #[inline]
    pub fn bucket(&self, index: u64) -> u16 {
        let i = index as usize;
        if self.header.bytes_per_bucket == 1 {
            self.payload[i] as u16
        } else {
            u16::from_le_bytes([self.payload[2 * i], self.payload[2 * i + 1]])
        }
    }

    /// The distances between this table's buckets, ready for clustering the street before.
    pub fn ground_metric(&self) -> Option<Metric> {
        let k = self.buckets();
        match &self.metric {
            MetricData::None => None,
            MetricData::Line { pos } => Some(Metric::Line(Line::new(pos.clone()))),
            MetricData::Matrix { d, embed } => Some(Metric::Matrix(Matrix::new(
                k,
                d.clone(),
                embed.clone(),
                self.header.embed_dim as usize,
            ))),
        }
    }

    /// Feeds the file's bytes, all but the checksum at the end, to `f` in pieces.
    fn pieces(&self, mut f: impl FnMut(&[u8])) {
        let header = serde_json::to_vec(&self.header).expect("the header is plain data");
        f(MAGIC);
        f(&FORMAT_VERSION.to_le_bytes());
        f(&(header.len() as u32).to_le_bytes());
        f(&header);
        f(&self.payload);
        let mut small = Vec::with_capacity(self.sizes.len() * 8);
        for &s in &self.sizes {
            small.extend_from_slice(&s.to_le_bytes());
        }
        f(&small);
        let mut put = |values: &[f32]| {
            small.clear();
            for &x in values {
                small.extend_from_slice(&x.to_le_bytes());
            }
            f(&small);
        };
        put(&self.equity);
        put(&self.centroids);
        match &self.metric {
            MetricData::None => {}
            MetricData::Line { pos } => put(pos),
            MetricData::Matrix { d, embed } => {
                put(d);
                put(embed);
            }
        }
    }

    /// The file's bytes.
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut out = Vec::with_capacity(self.payload.len() + self.centroids.len() * 4 + 4096);
        self.pieces(|piece| out.extend_from_slice(piece));
        let checksum = xxh64(&out);
        out.extend_from_slice(&checksum.to_le_bytes());
        out
    }

    /// The checksum the file ends with, as 16 hex digits.
    pub fn checksum(&self) -> String {
        let mut hash = Xxh64::new(0);
        self.pieces(|piece| hash.update(piece));
        format!("{:016x}", hash.finish())
    }

    /// Writes the table and returns the file's size in bytes. The file is written under a
    /// temporary name and renamed, so a stopped build never leaves half a table.
    pub fn save(&self, path: &Path) -> io::Result<u64> {
        let tmp = path.with_extension("abs.tmp");
        let mut file = io::BufWriter::with_capacity(1 << 20, std::fs::File::create(&tmp)?);
        let mut hash = Xxh64::new(0);
        let mut size = 8u64;
        let mut result = Ok(());
        self.pieces(|piece| {
            hash.update(piece);
            size += piece.len() as u64;
            if result.is_ok() {
                result = file.write_all(piece);
            }
        });
        result?;
        file.write_all(&hash.finish().to_le_bytes())?;
        file.into_inner().map_err(|e| e.into_error())?.sync_all()?;
        std::fs::rename(&tmp, path)?;
        Ok(size)
    }

    /// Reads a table and checks its checksum.
    pub fn load(path: &Path) -> io::Result<Table> {
        Table::read(path, true)
    }

    /// Reads a table without checking the checksum. The sizes are still checked.
    pub fn load_unchecked(path: &Path) -> io::Result<Table> {
        Table::read(path, false)
    }

    fn read(path: &Path, verify: bool) -> io::Result<Table> {
        let mut file = std::fs::File::open(path)?;
        let size = file.metadata()?.len() as usize;
        let mut bytes = Vec::with_capacity(size);
        file.read_to_end(&mut bytes)?;
        Table::from_bytes(bytes, verify).map_err(|e| bad(format!("{}: {e}", path.display())))
    }

    /// Parses a file's bytes.
    pub fn from_bytes(mut bytes: Vec<u8>, verify: bool) -> io::Result<Table> {
        if bytes.len() < 24 || &bytes[..8] != MAGIC {
            return Err(bad("not an abstraction table"));
        }
        let version = u32::from_le_bytes(bytes[8..12].try_into().unwrap());
        if version != FORMAT_VERSION {
            return Err(bad(format!(
                "table format {version}, this build reads format {FORMAT_VERSION}: rebuild the table"
            )));
        }
        let header_len = u32::from_le_bytes(bytes[12..16].try_into().unwrap()) as usize;
        if bytes.len() < 24 + header_len {
            return Err(bad("file cut short"));
        }
        let header: Header =
            serde_json::from_slice(&bytes[16..16 + header_len]).map_err(|e| bad(format!("bad header: {e}")))?;
        let k = header.buckets as usize;
        let hands = header.hands as usize;
        if k == 0 || !(1..=2).contains(&header.bytes_per_bucket) || (header.bytes_per_bucket == 1) != (k <= 256) {
            return Err(bad("bad bucket count in the header"));
        }
        let payload_len = hands * header.bytes_per_bucket as usize;
        let metric_len = match header.metric {
            MetricKind::None => 0,
            MetricKind::Line => k * 4,
            MetricKind::Matrix => (k * k + k * header.embed_dim as usize) * 4,
        };
        let centroid_len = k * header.centroid_dim as usize * 4;
        let body = 16 + header_len;
        let expected = body + payload_len + k * 8 + k * 4 + centroid_len + metric_len + 8;
        if bytes.len() != expected {
            return Err(bad(format!("file is {} bytes, the header says {expected}", bytes.len())));
        }
        if verify {
            let stored = u64::from_le_bytes(bytes[expected - 8..].try_into().unwrap());
            let actual = xxh64(&bytes[..expected - 8]);
            if stored != actual {
                return Err(bad(format!(
                    "checksum mismatch: file says {stored:016x}, contents give {actual:016x}"
                )));
            }
        }
        let mut at = body + payload_len;
        let sizes: Vec<u64> = bytes[at..at + k * 8]
            .chunks_exact(8)
            .map(|b| u64::from_le_bytes(b.try_into().unwrap()))
            .collect();
        at += k * 8;
        let equity = floats(&bytes[at..at + k * 4]);
        at += k * 4;
        let centroids = floats(&bytes[at..at + centroid_len]);
        at += centroid_len;
        let metric = match header.metric {
            MetricKind::None => MetricData::None,
            MetricKind::Line => MetricData::Line {
                pos: floats(&bytes[at..at + k * 4]),
            },
            MetricKind::Matrix => MetricData::Matrix {
                d: floats(&bytes[at..at + k * k * 4]),
                embed: floats(&bytes[at + k * k * 4..at + metric_len]),
            },
        };
        if verify {
            let largest = if header.bytes_per_bucket == 1 {
                bytes[body..body + payload_len].iter().copied().max().unwrap_or(0) as usize
            } else {
                bytes[body..body + payload_len]
                    .chunks_exact(2)
                    .map(|b| u16::from_le_bytes([b[0], b[1]]))
                    .max()
                    .unwrap_or(0) as usize
            };
            if largest >= k {
                return Err(bad("a bucket number is out of range"));
            }
        }
        // Keep only the buckets, without copying them.
        bytes.truncate(body + payload_len);
        bytes.drain(..body);
        Ok(Table {
            header,
            payload: bytes,
            sizes,
            equity,
            centroids,
            metric,
        })
    }

    /// Reads only the header of a table file.
    pub fn read_header(path: &Path) -> io::Result<Header> {
        let mut file = std::fs::File::open(path)?;
        let mut start = [0u8; 16];
        file.read_exact(&mut start)?;
        if &start[..8] != MAGIC {
            return Err(bad("not an abstraction table"));
        }
        let len = u32::from_le_bytes(start[12..16].try_into().unwrap()) as usize;
        let mut header = vec![0u8; len];
        file.read_exact(&mut header)?;
        serde_json::from_slice(&header).map_err(|e| bad(format!("bad header: {e}")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample(k: usize, hands: usize) -> Table {
        let header = Header {
            format: 0,
            built_by: String::new(),
            street: Street::Turn,
            ranks: 13,
            hands: 0,
            buckets: 0,
            bytes_per_bucket: 0,
            centroid_dim: 0,
            metric: MetricKind::None,
            embed_dim: 0,
            seed: 9,
            settings: StreetSettings {
                buckets: k as u32,
                feature: Feature::NextBuckets,
                kmeans: KMeansSettings::default(),
            },
            built_from: "test".into(),
            opponent_clusters: vec![],
            iterations: 3,
            trained_on: hands as u64,
            cost: 0.125,
        };
        let buckets: Vec<u16> = (0..hands).map(|i| (i * 7 % k) as u16).collect();
        let mut d = vec![0f32; k * k];
        for i in 0..k {
            for j in 0..k {
                d[i * k + j] = (i as f32 - j as f32).abs();
            }
        }
        Table::new(
            header,
            &buckets,
            (0..k as u64).collect(),
            (0..k).map(|i| i as f32 / k as f32).collect(),
            (0..k * 3).map(|i| i as f32).collect(),
            MetricData::Matrix {
                d,
                embed: (0..k).map(|i| i as f32).collect(),
            },
        )
    }

    #[test]
    fn bytes_round_trip_narrow_and_wide() {
        for k in [5usize, 256, 257, 1000] {
            let table = sample(k, 5000);
            let bytes = table.to_bytes();
            let back = Table::from_bytes(bytes.clone(), true).unwrap();
            assert_eq!(back.header, table.header);
            assert_eq!(back.header.bytes_per_bucket, if k > 256 { 2 } else { 1 });
            assert_eq!(back.sizes, table.sizes);
            assert_eq!(back.equity, table.equity);
            assert_eq!(back.centroids, table.centroids);
            assert_eq!(back.metric, table.metric);
            for i in 0..5000 {
                assert_eq!(back.bucket(i), table.bucket(i));
                assert_eq!(back.bucket(i) as usize, i as usize * 7 % k);
            }
            assert_eq!(back.to_bytes(), bytes);
            assert!(back.ground_metric().is_some());
        }
    }

    #[test]
    fn damage_is_noticed() {
        let table = sample(12, 300);
        let good = table.to_bytes();
        // A flipped bit anywhere fails the checksum (or the header, or the sizes).
        for at in [9usize, 20, good.len() / 2, good.len() - 20, good.len() - 1] {
            let mut bytes = good.clone();
            bytes[at] ^= 0x10;
            assert!(Table::from_bytes(bytes, true).is_err(), "byte {at}");
        }
        let mut short = good.clone();
        short.truncate(good.len() - 5);
        assert!(Table::from_bytes(short, true).is_err());
        let mut long = good.clone();
        long.push(0);
        assert!(Table::from_bytes(long, false).is_err());
        // Without the check, a flipped bucket byte goes through.
        let mut bytes = good.clone();
        let at = good.len() / 3;
        bytes[at] ^= 1;
        assert!(Table::from_bytes(bytes.clone(), false).is_ok());
        assert!(Table::from_bytes(bytes, true).unwrap_err().to_string().contains("checksum"));
    }

    #[test]
    fn another_format_version_is_refused() {
        let mut bytes = sample(4, 10).to_bytes();
        bytes[8] = 99;
        let error = Table::from_bytes(bytes, false).unwrap_err().to_string();
        assert!(error.contains("format 99"), "{error}");
    }

    #[test]
    fn saves_and_loads_a_file() {
        let dir = std::env::temp_dir().join(format!("abstraction-table-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join(Street::Turn.file_name());
        let table = sample(300, 2000);
        let size = table.save(&path).unwrap();
        assert_eq!(size, std::fs::metadata(&path).unwrap().len());
        let back = Table::load(&path).unwrap();
        assert_eq!(back.checksum(), table.checksum());
        assert_eq!(Table::read_header(&path).unwrap(), table.header);
        assert_eq!(Table::load_unchecked(&path).unwrap().bucket(1999), table.bucket(1999));
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
