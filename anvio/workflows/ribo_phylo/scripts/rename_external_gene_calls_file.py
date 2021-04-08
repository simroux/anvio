from Bio import SeqIO

import pandas as pd
import numpy as np
import glob
import os.path

# Import fasta header index
#----------------------------
reformat_report = pd.read_csv(snakemake.input.reformat_file_all, \
                  sep="\t", \
                  index_col=False, \
                  names=["new_header", "header"])
# print(reformat_report.head)
external_gene_calls = pd.read_csv(snakemake.input.external_gene_calls_all, \
                  delim_whitespace=True, \
                  index_col=False)

headers = pd.read_csv(snakemake.input.headers, \
                  sep="\t", \
                  index_col=False,
                  names=["contig"])
# print(headers)

# fasta_df = pd.DataFrame({'header': [], 'sequence': []})

# for seq_record in SeqIO.parse(snakemake.input.SCGs_nt, "fasta"):
#     fasta_df = fasta_df.append({'header': str(seq_record.description), 'sequence': str(seq_record.seq)}, ignore_index=True)


# reformat_report["sample"] = reformat_report['header'].str.split("bin_id:|\|source:", expand=True)[1].astype(str).str.strip("-contigs")
reformat_report["sample_contig"] = reformat_report['header'].str.split("contig:|\|gene_callers_id:", expand=True)[1].astype(str)
reformat_report["gene_callers_id"] = reformat_report['header'].str.split("gene_callers_id:|\|start:", expand=True)[1].astype(str)
reformat_report["sample_name"] = reformat_report['header'].str.split("bin_id:|\|source:", expand=True)[1].astype(str)
reformat_report['sample_name'] = reformat_report['sample_name'].map(lambda x: x.rstrip('-contigs'))
reformat_report["contig"] =  reformat_report['sample_name'] + "_" + reformat_report['sample_contig'] + "_" + reformat_report['gene_callers_id'].astype(str)
reformat_report = reformat_report.drop(columns=['gene_callers_id'])
# print(reformat_report.head)

# Join
# print(reformat_report.contig)
# print(external_gene_calls)
external_gene_calls_filtered = reformat_report.merge(external_gene_calls, on="contig", how="inner").drop(columns=['header', 'sample_name', 'contig']).rename(columns={'new_header': 'contig'})
external_gene_calls_filtered_ed = external_gene_calls_filtered.merge(headers, on="contig", how="inner")
external_gene_calls_filtered_final = external_gene_calls_filtered_ed[["gene_callers_id", "contig", "start", "stop", "direction", "partial", "call_type", "source", "version", "aa_sequence"]]
external_gene_calls_filtered_final['gene_callers_id'] = external_gene_calls_filtered_ed.index

external_gene_calls_filtered_final.to_csv(snakemake.output.external_gene_calls_renamed, \
           sep="\t", \
           index=False, \
           header=True, \
           na_rep="NA")