# -*- coding: utf-8
# pylint: disable=line-too-long
"""
    Classes to classify genes based on coverages across metagenomes.

    anvi-alons-classifier is the default client using this module
"""


import os
import anvio
import numpy as np
import scipy as sp
import pandas as pd
import matplotlib
matplotlib.use('pdf')
import matplotlib.pyplot as plt
import anvio.terminal as terminal
import anvio.summarizer as summarizer
import anvio.filesnpaths as filesnpaths

from math import ceil
from math import floor
from scipy.stats import norm
from anvio.errors import ConfigError
from anvio.dbops import ProfileSuperclass
from matplotlib.backends.backend_pdf import PdfPages


__author__ = "Alon Shaiber"
__copyright__ = "Copyright 2017, The anvio Project"
__credits__ = []
__license__ = "GPL 3.0"
__version__ = anvio.__version__
__maintainer__ = "Alon Shaiber"
__email__ = "alon.shaiber@gmail.com"


run = terminal.Run()
progress = terminal.Progress()
pp = terminal.pretty_print

def get_coverage_values_per_nucleotide(split_coverage_values_per_nt_dict, samples=None):
    """ Helper function that accepts a split_coverage_values_per_nt_dict and returns a dictionary with
    samples as keys and the concatenated coverage values for all splits as one array
    """
    progress.new('Merging coverage values accross splits')
    d = {}
    if samples is None:
        samples = split_coverage_values_per_nt_dict[next(iter(split_coverage_values_per_nt_dict.keys()))].keys()
    number_of_samples = len(samples)
    number_of_finished = 0
    for sample in samples:
        d[sample] = np.empty([1,0])
        for split in split_coverage_values_per_nt_dict:
            d[sample] = np.append(d[sample],split_coverage_values_per_nt_dict[split][sample])
        #d[sample] = np.array(d[sample])
        number_of_finished += 1
        progress.update("Finished sample %d of %d" % (number_of_finished,number_of_samples))
    progress.end()
    return d


def get_non_outliers(v):
    """ returns the non-outliers according to the interqurtile range (IQR) for the input pandas series"""
    q1 = np.percentile(v, 25)
    q3 = np.percentile(v, 75)
    IQR = q3 - q1
    # The non-outliers are non-zero values that are in the IQR (positions that are zero are considered outliers
    # even if the IQR includes zero)
    non_outliers_indices = np.where((v >= q1 - 1.5 * IQR) & (v <= q3 + 1.5 * IQR) & (v > 0))[0]
    mean = np.mean(v[non_outliers_indices])
    std = np.std(v[non_outliers_indices])
    return non_outliers_indices, mean, std


def get_new_mean(_mean, x, N):
    """ Helper function to calculate a new mean after removing one data point."""
    new_mean = N/(N-1)*_mean - 1/(N-1)*x
    return new_mean


def get_new_std(_mean, _std, x, ):
    p = N/(N-1)
    new_std = np.sqrt(p * _std**2 - ((_mean - x)**2)*p/(N-1))
    
def single_distribution_EM(v, _indices=None, _mean=None, _std=None):
    if _indices is None:
        _indices = set(range(len(v)))
    else:
        _indices = set(_indices)
    if _mean is None:
        _mean = np.mean(v[_indices])
    if _std is None:
        _std = np.std(v[_indices])

    converged = False
    while not convereged:
        w = v[_indices]
        N = len(_indices)
        # creating the pdf function to apply
        _pdf = lambda x: norm.pdf(x, _mean, _std)
        # applying pdf to all values
        w_pdf = np.apply_along_axis(_pdf, 0, w)
        likelihood = np.sum(w_pdf)
        i = np.argmin(w_pdf)
        # translating the index to be relative to v
        i = _indices[i]
        new_mean = get_new_mean(_mean, v[i], N)
        new_std = get_new_std(_mean, _std, v[i], N)
        new_indices = _indices - {i}
        np.apply_along_axis(_pdf, 0, w)


class mcg:
    def __init__(self, args, run=run, progress=progress):
        self.run = run
        self.progress = progress

        A = lambda x: args.__dict__[x] if x in args.__dict__ else None
        self.gene_coverages_data_file_path = A('data_file')
        self.gene_detections_data_file_path = A('gene_detection_data_file')
        self.profile_db_path = A('profile_db')
        self.output_file_prefix = A('output_file_prefix')
        self.alpha = A('alpha')
        self.beta = A('beta')
        self.gamma = A('gamma')
        self.eta = A('eta')
        self.zeta = A('zeta')
        self.additional_layers_to_append = A('additional_layers_to_append')
        self.samples_information_to_append = A('samples_information_to_append')
        self.collection_name = A('collection_name')
        self.bin_id = A('bin_id')
        self.bin_ids_file_path = A('bin_ids_file')
        self.exclude_samples = A('exclude_samples')
        self.profile_db = {}
        self.coverage_values_per_nt = {}
        self.gene_coverages = pd.DataFrame.empty
        self.gene_detections = pd.DataFrame.empty
        self.samples = {}
        self.positive_samples = []
        self.number_of_positive_samples = None
        self.negative_samples = pd.DataFrame.empty
        self.number_of_negative_samples = None
        self.gene_class_information = pd.DataFrame.empty
        self.samples_information = pd.DataFrame.empty
        self.gene_presence_absence_in_samples = pd.DataFrame.empty
        self.gene_coverages_filtered = pd.DataFrame.empty
        self.additional_description = ''
        self.total_length = None

        if self.exclude_samples:
            # check that there is a file like this
            filesnpaths.is_file_exists(self.exclude_samples)
            self.samples_to_exclude = set([l.split('\t')[0].strip() for l in open(args.exclude_samples, 'rU').readlines()])
            run.info('Excluding Samples', 'The following samples will be excluded: %s' % self.samples_to_exclude,)
        else:
            self.samples_to_exclude = set([])

        # run sanity check on all input arguments
        self.sanity_check()

        if self.profile_db_path is None:
            # TODO: this will probably be removed because we don't save the coverage information in nucleotide level.
            pass
        else:
            # load sample list and gene_coverage_dict from the merged profile db
            args.init_gene_coverages = True
            if self.collection_name:
                self.summary = summarizer.ProfileSummarizer(args)
                self.summary.init()
                self.samples = set(self.summary.p_meta['samples']) - self.samples_to_exclude
            else:
                self.profile_db = ProfileSuperclass(args)
                self.samples = set(self.profile_db.p_meta['samples']) - self.samples_to_exclude
                self.profile_db.init_split_coverage_values_per_nt_dict()
                self.coverage_values_per_nt = get_coverage_values_per_nucleotide(self.profile_db.split_coverage_values_per_nt_dict, self.samples)

                self.profile_db.init_gene_coverages_and_detection_dicts()
                self.gene_coverages = pd.DataFrame.from_dict(self.profile_db.gene_coverages_dict, orient='index', dtype=float)
                # Removing samples if the user asked to exclude them
                self.gene_coverages.drop(self.samples_to_exclude, axis=1, inplace=True)
                self.Ng = len(self.gene_coverages.index)
                self.gene_detections = pd.DataFrame.from_dict(self.profile_db.gene_detection_dict, orient='index', dtype=float)
                self.gene_detections.drop(self.samples_to_exclude, axis=1, inplace=True)
                # getting the total length of all contigs 
                self.total_length = self.profile_db.p_meta['total_length']


    def check_if_valid_portion_value(self, arg_name,arg_value):
        """ Helper function to verify that an argument has a valid value for a non-zero portion (i.e. greater than zero and a max of 1)"""
        if arg_value <= 0 or arg_value > 1:
            raise ConfigError("%s value must be greater than zero and a max of 1, the value you supplied %s" % (arg_name,arg_value))
       
    def sanity_check(self):
        """Basic sanity check for class inputs"""

        if self.profile_db_path is None and self.gene_coverages_data_file_path is None:
            raise ConfigError("You must provide either a profile.db or a gene coverage self.gene_coverages_filtered data file")

        if self.profile_db_path and self.gene_coverages_data_file_path:
            raise ConfigError("You provided both a profile database and a gene coverage self.gene_coverages_filtered data file, you \
            must provide only one or the other (hint: if you have a profile database, the use that")

        # checking output file
        filesnpaths.is_output_file_writable(self.output_file_prefix + '-additional-layers.txt', ok_if_exists=False)

        # checking alpha
        if not isinstance(self.alpha, float):
            raise ConfigError("alpha value must be a type float.")
        # alpha must be a min of 0 and smaller than 0.5
        if self.alpha < 0 or self.alpha >= 0.5:
            raise ConfigError("alpha must be a minimum of 0 and smaller than 0.5")

        # Checking beta
        if not isinstance(self.beta, float):
            raise ConfigError("beta value must be a type float.")
        self.check_if_valid_portion_value("beta", self.beta)

        # Checking gamma
        if not isinstance(self.gamma, float):
            raise ConfigError("Gamma value must be a type float.")
        self.check_if_valid_portion_value("gamma", self.gamma)

        # Checking eta
        self.check_if_valid_portion_value("eta", self.eta) 

        if self.collection_name:
            if not self.profile_db_path:
                raise ConfigError("You specified a collection name %s, but you provided a gene coverage self.gene_coverages_filtered data file \
                 collections are only available when working with a profile database." % self.collection_name)


    def init_sample_detection_information(self):
        """ Determine  positive, negative, and ambiguous samples with the genome detection information 
        (--alpha, --genome-detection-uncertainty)
        """

        MDG_samples_information_table_name      = 'MDG_classifier_samples_information'
        MDG_samples_information_table_structure = ['samples', 'presence', 'detection', 'number_of_taxon_specific_core_detected']
        MDG_samples_information_table_types     = ['str', 'bool', 'int', 'int']
        # create an empty dataframe
        samples_information = pd.DataFrame(index=self.samples, columns=MDG_samples_information_table_structure[1:])
        positive_samples = []
        negative_samples = []
        
        self.progress.new("Setting presence/absence in samples")        
        num_samples, counter = len(self.samples), 1
        detection = {}
        for sample in self.samples:
            if num_samples > 100 and counter % 100 == 0:
                self.progress.update('%d of %d samples...' % (counter, num_samples))
            detection[sample] = np.count_nonzero(self.coverage_values_per_nt[sample]) / self.total_length
            if detection[sample] >= 0.5 + self.alpha:
                positive_samples.append(sample)
                samples_information['presence'][sample] = True
            elif detection[sample] <= 0.5 - self.alpha:
                negative_samples.append(sample)
                samples_information['presence'][sample] = False
            else:
                samples_information['presence'][sample] = None
            samples_information['detection'][sample] = detection[sample]
            counter += 1
        self.progress.end()

        self.positive_samples = positive_samples
        self.number_of_positive_samples = len(self.positive_samples)
        self.negative_samples = negative_samples
        self.samples_information = samples_information
        self.run.warning('The number of positive samples is %s' % self.number_of_positive_samples)
        self.run.warning('The number of negative samples is %s' % len(self.negative_samples))



    def plot_TS(self, non_outliers_indices, mean_TS, std_TS):
        """ Creates a pdf file with the following plots for each sample the sorted nucleotide coverages \
        (with a the outliers in red and non-outliers in blue), and a histogram of coverages for the non-outliers"""
        # Creating a dircetory for the plots. If running on bins, each bin would be in a separate sub-directory
        additional_description = ''
        if self.additional_description:
            additional_description = '-' + self.additional_description
        plot_dir = self.output_file_prefix + '-TS-plots' + '/'
        os.makedirs(plot_dir, exist_ok=True)
        self.progress.new('Saving figures of taxon specific distributions to pdf')
        number_of_fininshed = 0
        for sample in self.positive_samples:
            coverages_pdf_output = plot_dir + sample + additional_description + '-coverages.pdf'
            pdf_output_file = PdfPages(coverages_pdf_output)
            v = self.coverage_values_per_nt[sample]
            # Using argsort so we can use the non_oulier indices
            sorting_indices = np.argsort(v)
            # we would need the reverse of the sorting of the indices to create the x axis for the non-outliers
            reverse_sorted_indices = np.zeros(len(sorting_indices))
            reverse_sorted_indices[sorting_indices] = range(len(reverse_sorted_indices))

            # plotting the ordered coverage values (per nucleotide)
            # the non-outliers are plotted in blue
            # the outlier values are plotted in red
            fig = plt.figure()
            ax = fig.add_subplot(111, rasterized=True)
            ax.set_xlabel = 'Nucleotide Number (ordered)'
            ax.set_ylabel = r'$Nucleotide Coverage^2$'
            x1 = range(len(v)) # FIXME: this shouldn't be in the loop (only here because I need to fix the mock data)
            x2 = reverse_sorted_indices[non_outliers_indices[sample]]
            y2 = v[non_outliers_indices[sample]]
            # plot all in red
            ax.semilogy(x1,v[sorting_indices],'r.', rasterized=True)
            # plot on top the non-outliers in blue
            ax.semilogy(x2,v[non_outliers_indices[sample]],'b.', rasterized=True)
            fig.suptitle("%s - sorted coverage values with outliers" % sample)
            plt.savefig(pdf_output_file, format='pdf')
            plt.close()

            # plotting a histogram of the non-outliers
            # This would allow to see if they resemble a normal distribution
            hist_range = (min(v[non_outliers_indices[sample]]),max(v[non_outliers_indices[sample]]))
            # computing the number of bins so that the width of a bin is ~1/4 of the standard deviation
            # FIXME: need to make it so the bins are only of integers (so the smallest bin is of width 1
            # and that bins are integers)
            number_of_hist_bins = np.ceil((hist_range[1] - hist_range[0]) / (std_TS[sample]/4)).astype(int) # setting the histogram bins to be of the width of a quarter of std
            fig = plt.figure()
            ax = fig.add_subplot(111, rasterized=True)
            ax.set_xlabel = 'Coverage'
            ax.hist(v[non_outliers_indices[sample]], number_of_hist_bins,hist_range, rasterized=True)
            fig.suptitle("%s - histogram of non-outliers" % sample)
            # adding the mean and std of the non-outliers as text to the plot
            text_for_hist = u'$\mu = %d$\n $\sigma = %d$' % (mean_TS[sample], std_TS[sample])
            ax.text(0.8, 0.9, text_for_hist, ha='center', va='center', transform=ax.transAxes)
            plt.savefig(pdf_output_file, format='pdf')
            plt.close()
            # close the pdf file
            pdf_output_file.close()
            number_of_fininshed += 1
            self.progress.update("Finished %d of %d" % (number_of_fininshed, self.number_of_positive_samples))
        self.progress.end()


    def get_taxon_specific_genes_in_samples(self):
        """ Use only positive samples to identify the single copy taxon specific genes in each sample:
            
        """
        non_outliers_indices = {}
        mean_TS = {}
        std_TS = {}
        num_samples, counter = len(self.samples), 1
        self.progress.new("Finding taxon specific genes in samples")
        for sample in self.positive_samples:
            if num_samples > 100 and counter % 100 == 0:
                self.progress.update('%d of %d samples...' % (counter, num_samples))
            # loop through positive samples
            # get the indexes of the non outliers and a pdf for the coverage of the single copy core genes
            non_outliers_indices[sample], mean_TS[sample], std_TS[sample] = get_non_outliers(self.coverage_values_per_nt[sample])
#            TS_nucs[sample], mean_TS[sample], std_TS[sample] = single_distribution_EM(self.coverage_values_per_nt[sample], non_outliers_indices[sample], mean_TS[sample], std_TS[sample])
            self.run.info_single('The mean and std in sample %s are: %s, %s respectively' % (sample, mean_TS[sample], std_TS[sample]))
            self.run.info_single('The number of non_outliers is %s of %s' % (len(non_outliers_indices[sample]), self.total_length))
        self.progress.end()
        self.plot_TS(non_outliers_indices,mean_TS,std_TS)


    def get_gene_classes(self):
        """ The main process of this class - computes the class information for each gene"""
        # need to start a new gene_class_information dict
        # this is due to the fact that if the algorithm is ran on a list of bins then this necessary
        self.gene_class_information = pd.DataFrame(index=self.gene_coverages.index,columns=['gene_class'])

        # set the presence/absence values for samples
        self.init_sample_detection_information()

        # find the taxon-specific genes for each sample
        self.get_taxon_specific_genes_in_samples()


    def get_coverage_and_detection_dict(self,bin_id):
        _bin = summarizer.Bin(self.summary, bin_id)
        self.gene_coverages = pd.DataFrame.from_dict(_bin.gene_coverages, orient='index', dtype=float)
        self.gene_coverages.drop(self.samples_to_exclude, axis=1, inplace=True)
        self.Ng = len(self.gene_coverages.index)
        self.coverage_values_per_nt = get_coverage_values_per_nucleotide(_bin.summary.split_coverage_values_per_nt_dict, self.samples)
        self.gene_detections = pd.DataFrame.from_dict(_bin.gene_detection, orient='index', dtype=float)
        self.gene_detections.drop(self.samples_to_exclude, axis=1, inplace=True)
        self.total_length = _bin.total_length


    def classify(self):
        if self.collection_name:
            bin_names_in_collection = self.summary.bin_ids
            if self.bin_ids_file_path:
                filesnpaths.is_file_exists(self.bin_ids_file_path)
                bin_names_of_interest = [line.strip() for line in open(self.bin_ids_file_path).readlines()]

                missing_bins = [b for b in bin_names_of_interest if b not in bin_names_in_collection]
                if len(missing_bins):
                    raise ConfigError("Some bin names you declared do not appear to be in the collection %s. \
                                        These are the bins that are missing: %s, these are the bins that are \
                                        actually in your collection: %s" % (self.collection_name,missing_bins,bin_names_in_collection))
            elif self.bin_id:
                if self.bin_id not in bin_names_in_collection:
                    raise ConfigError("The bin you declared, %s, does not appear to be in the collection %s." \
                                      % (self.bin_id, self.collection_name))
                bin_names_of_interest = [self.bin_id]
            else:
                bin_names_of_interest = bin_names_in_collection

            for bin_id in bin_names_of_interest:
                self.run.info_single('Classifying genes in bin: %s' % bin_id)
                self.get_coverage_and_detection_dict(bin_id)
                self.additional_description = bin_id
                self.get_gene_classes()
                #self.save_gene_class_information_in_additional_layers(bin_id)
                #self.save_samples_information(bin_id)
                #if self.store_gene_detections_and_gene_coverages_tables:
                #    self.save_gene_detection_and_coverage(bin_id)

        else:
            # No collection provided so running on the entire detection table
            self.get_gene_classes()
            #self.save_gene_class_information_in_additional_layers()
            #self.save_samples_information()
