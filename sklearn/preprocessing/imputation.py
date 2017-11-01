# Authors: Nicolas Tresegnie <nicolas.tresegnie@gmail.com>,
#          Sergey Feldman <sergeyfeldman@gmail.com>
# License: BSD 3 clause

import warnings
from time import time

import numpy as np
import numpy.ma as ma
from scipy import sparse
from scipy import stats

from ..base import BaseEstimator, TransformerMixin
from ..base import clone
from ..dummy import DummyRegressor
from ..externals import six
from ..externals.funcsigs import signature
from ..preprocessing import normalize
from ..utils import check_array, check_random_state
from ..utils.sparsefuncs import _get_median
from ..utils.validation import FLOAT_DTYPES
from ..utils.validation import check_is_fitted

zip = six.moves.zip
map = six.moves.map

__all__ = [
    'Imputer',
    'MICEImputer',
]


def _get_mask(X, value_to_mask):
    """Compute the boolean mask X == missing_values."""
    if value_to_mask == "NaN" or np.isnan(value_to_mask):
        return np.isnan(X)
    else:
        return X == value_to_mask


def _most_frequent(array, extra_value, n_repeat):
    """Compute the most frequent value in a 1d array extended with
       [extra_value] * n_repeat, where extra_value is assumed to be not part
       of the array."""
    # Compute the most frequent value in array only
    if array.size > 0:
        mode = stats.mode(array)
        most_frequent_value = mode[0][0]
        most_frequent_count = mode[1][0]
    else:
        most_frequent_value = 0
        most_frequent_count = 0

    # Compare to array + [extra_value] * n_repeat
    if most_frequent_count == 0 and n_repeat == 0:
        return np.nan
    elif most_frequent_count < n_repeat:
        return extra_value
    elif most_frequent_count > n_repeat:
        return most_frequent_value
    elif most_frequent_count == n_repeat:
        # Ties the breaks. Copy the behaviour of scipy.stats.mode
        if most_frequent_value < extra_value:
            return most_frequent_value
        else:
            return extra_value


class Imputer(BaseEstimator, TransformerMixin):
    """Imputation transformer for completing missing values.

    Read more in the :ref:`User Guide <imputation>`.

    Parameters
    ----------
    missing_values : integer or "NaN", optional (default="NaN")
        The placeholder for the missing values. All occurrences of
        `missing_values` will be imputed. For missing values encoded as np.nan,
        use the string value "NaN".

    strategy : string, optional (default="mean")
        The imputation strategy.

        - If "mean", then replace missing values using the mean along
          the axis.
        - If "median", then replace missing values using the median along
          the axis.
        - If "most_frequent", then replace missing using the most frequent
          value along the axis.

    axis : integer, optional (default=0)
        The axis along which to impute.

        - If `axis=0`, then impute along columns.
        - If `axis=1`, then impute along rows.

    verbose : integer, optional (default=0)
        Controls the verbosity of the imputer.

    copy : boolean, optional (default=True)
        If True, a copy of X will be created. If False, imputation will
        be done in-place whenever possible. Note that, in the following cases,
        a new copy will always be made, even if `copy=False`:

        - If X is not an array of floating values;
        - If X is sparse and `missing_values=0`;
        - If `axis=0` and X is encoded as a CSR matrix;
        - If `axis=1` and X is encoded as a CSC matrix.

    Attributes
    ----------
    statistics_ : array of shape (n_features,)
        The imputation fill value for each feature if axis == 0.

    Notes
    -----
    - When ``axis=0``, columns which only contained missing values at `fit`
      are discarded upon `transform`.
    - When ``axis=1``, an exception is raised if there are rows for which it is
      not possible to fill in the missing values (e.g., because they only
      contain missing values).
    """
    def __init__(self, missing_values="NaN", strategy="mean",
                 axis=0, verbose=0, copy=True):
        self.missing_values = missing_values
        self.strategy = strategy
        self.axis = axis
        self.verbose = verbose
        self.copy = copy

    def fit(self, X, y=None):
        """Fit the imputer on X.

        Parameters
        ----------
        X : {array-like, sparse matrix}, shape (n_samples, n_features)
            Input data, where ``n_samples`` is the number of samples and
            ``n_features`` is the number of features.

        Returns
        -------
        self : Imputer
            Returns self.
        """
        # Check parameters
        allowed_strategies = ["mean", "median", "most_frequent"]
        if self.strategy not in allowed_strategies:
            raise ValueError("Can only use these strategies: {0} "
                             " got strategy={1}".format(allowed_strategies,
                                                        self.strategy))

        if self.axis not in [0, 1]:
            raise ValueError("Can only impute missing values on axis 0 and 1, "
                             " got axis={0}".format(self.axis))

        # Since two different arrays can be provided in fit(X) and
        # transform(X), the imputation data will be computed in transform()
        # when the imputation is done per sample (i.e., when axis=1).
        if self.axis == 0:
            X = check_array(X, accept_sparse='csc', dtype=np.float64,
                            force_all_finite=False)

            if sparse.issparse(X):
                self.statistics_ = self._sparse_fit(X,
                                                    self.strategy,
                                                    self.missing_values,
                                                    self.axis)
            else:
                self.statistics_ = self._dense_fit(X,
                                                   self.strategy,
                                                   self.missing_values,
                                                   self.axis)

        return self

    def _sparse_fit(self, X, strategy, missing_values, axis):
        """Fit the transformer on sparse data."""
        # Imputation is done "by column", so if we want to do it
        # by row we only need to convert the matrix to csr format.
        if axis == 1:
            X = X.tocsr()
        else:
            X = X.tocsc()

        # Count the zeros
        if missing_values == 0:
            n_zeros_axis = np.zeros(X.shape[not axis], dtype=int)
        else:
            n_zeros_axis = X.shape[axis] - np.diff(X.indptr)

        # Mean
        if strategy == "mean":
            if missing_values != 0:
                n_non_missing = n_zeros_axis

                # Mask the missing elements
                mask_missing_values = _get_mask(X.data, missing_values)
                mask_valids = np.logical_not(mask_missing_values)

                # Sum only the valid elements
                new_data = X.data.copy()
                new_data[mask_missing_values] = 0
                X = sparse.csc_matrix((new_data, X.indices, X.indptr),
                                      copy=False)
                sums = X.sum(axis=0)

                # Count the elements != 0
                mask_non_zeros = sparse.csc_matrix(
                    (mask_valids.astype(np.float64),
                     X.indices,
                     X.indptr), copy=False)
                s = mask_non_zeros.sum(axis=0)
                n_non_missing = np.add(n_non_missing, s)

            else:
                sums = X.sum(axis=axis)
                n_non_missing = np.diff(X.indptr)

            # Ignore the error, columns with a np.nan statistics_
            # are not an error at this point. These columns will
            # be removed in transform
            with np.errstate(all="ignore"):
                return np.ravel(sums) / np.ravel(n_non_missing)

        # Median + Most frequent
        else:
            # Remove the missing values, for each column
            columns_all = np.hsplit(X.data, X.indptr[1:-1])
            mask_missing_values = _get_mask(X.data, missing_values)
            mask_valids = np.hsplit(np.logical_not(mask_missing_values),
                                    X.indptr[1:-1])

            # astype necessary for bug in numpy.hsplit before v1.9
            columns = [col[mask.astype(bool, copy=False)]
                       for col, mask in zip(columns_all, mask_valids)]

            # Median
            if strategy == "median":
                median = np.empty(len(columns))
                for i, column in enumerate(columns):
                    median[i] = _get_median(column, n_zeros_axis[i])

                return median

            # Most frequent
            elif strategy == "most_frequent":
                most_frequent = np.empty(len(columns))

                for i, column in enumerate(columns):
                    most_frequent[i] = _most_frequent(column,
                                                      0,
                                                      n_zeros_axis[i])

                return most_frequent

    def _dense_fit(self, X, strategy, missing_values, axis):
        """Fit the transformer on dense data."""
        X = check_array(X, force_all_finite=False)
        mask = _get_mask(X, missing_values)
        masked_X = ma.masked_array(X, mask=mask)

        # Mean
        if strategy == "mean":
            mean_masked = np.ma.mean(masked_X, axis=axis)
            # Avoid the warning "Warning: converting a masked element to nan."
            mean = np.ma.getdata(mean_masked)
            mean[np.ma.getmask(mean_masked)] = np.nan

            return mean

        # Median
        elif strategy == "median":
            if tuple(int(v) for v in np.__version__.split('.')[:2]) < (1, 5):
                # In old versions of numpy, calling a median on an array
                # containing nans returns nan. This is different is
                # recent versions of numpy, which we want to mimic
                masked_X.mask = np.logical_or(masked_X.mask,
                                              np.isnan(X))
            median_masked = np.ma.median(masked_X, axis=axis)
            # Avoid the warning "Warning: converting a masked element to nan."
            median = np.ma.getdata(median_masked)
            median[np.ma.getmaskarray(median_masked)] = np.nan

            return median

        # Most frequent
        elif strategy == "most_frequent":
            # scipy.stats.mstats.mode cannot be used because it will no work
            # properly if the first element is masked and if its frequency
            # is equal to the frequency of the most frequent valid element
            # See https://github.com/scipy/scipy/issues/2636

            # To be able access the elements by columns
            if axis == 0:
                X = X.transpose()
                mask = mask.transpose()

            most_frequent = np.empty(X.shape[0])

            for i, (row, row_mask) in enumerate(zip(X[:], mask[:])):
                row_mask = np.logical_not(row_mask).astype(np.bool)
                row = row[row_mask]
                most_frequent[i] = _most_frequent(row, np.nan, 0)

            return most_frequent

    def transform(self, X):
        """Impute all missing values in X.

        Parameters
        ----------
        X : {array-like, sparse matrix}, shape = [n_samples, n_features]
            The input data to complete.
        """
        if self.axis == 0:
            check_is_fitted(self, 'statistics_')
            X = check_array(X, accept_sparse='csc', dtype=FLOAT_DTYPES,
                            force_all_finite=False, copy=self.copy)
            statistics = self.statistics_
            if X.shape[1] != statistics.shape[0]:
                raise ValueError("X has %d features per sample, expected %d"
                                 % (X.shape[1], self.statistics_.shape[0]))

        # Since two different arrays can be provided in fit(X) and
        # transform(X), the imputation data need to be recomputed
        # when the imputation is done per sample
        else:
            X = check_array(X, accept_sparse='csr', dtype=FLOAT_DTYPES,
                            force_all_finite=False, copy=self.copy)

            if sparse.issparse(X):
                statistics = self._sparse_fit(X,
                                              self.strategy,
                                              self.missing_values,
                                              self.axis)

            else:
                statistics = self._dense_fit(X,
                                             self.strategy,
                                             self.missing_values,
                                             self.axis)

        # Delete the invalid rows/columns
        invalid_mask = np.isnan(statistics)
        valid_mask = np.logical_not(invalid_mask)
        valid_statistics = statistics[valid_mask]
        valid_statistics_indexes = np.flatnonzero(valid_mask)
        missing = np.arange(X.shape[not self.axis])[invalid_mask]

        if self.axis == 0 and invalid_mask.any():
            if self.verbose:
                warnings.warn("Deleting features without "
                              "observed values: %s" % missing)
            X = X[:, valid_statistics_indexes]
        elif self.axis == 1 and invalid_mask.any():
            raise ValueError("Some rows only contain "
                             "missing values: %s" % missing)

        # Do actual imputation
        if sparse.issparse(X) and self.missing_values != 0:
            mask = _get_mask(X.data, self.missing_values)
            indexes = np.repeat(np.arange(len(X.indptr) - 1, dtype=np.int),
                                np.diff(X.indptr))[mask]

            X.data[mask] = valid_statistics[indexes].astype(X.dtype,
                                                            copy=False)
        else:
            if sparse.issparse(X):
                X = X.toarray()

            mask = _get_mask(X, self.missing_values)
            n_missing = np.sum(mask, axis=self.axis)
            values = np.repeat(valid_statistics, n_missing)

            if self.axis == 0:
                coordinates = np.where(mask.transpose())[::-1]
            else:
                coordinates = mask

            X[coordinates] = values

        return X


class MICEImputer(BaseEstimator, TransformerMixin):
    """MICE (Multivariate Imputations by Chained Equations) transformer to
    impute missing values.

    Basic implementation of MICE package from R. This version assumes all of
    the features are Gaussian.

    Parameters
    ----------
    missing_values : int or "NaN", optional (default="NaN")
        The placeholder for the missing values. All occurrences of
        `missing_values` will be imputed. For missing values encoded as
        np.nan, use the string value "NaN".

    imputation_order : str, optional (default="monotone")
        The order in which the features will be imputed.
        - "monotone" - From features with fewest missing values to most.
        - "revmonotone" - From features with most missing values to fewest.
        - "roman" - Left to right.
        - "arabic" - Right to left.
        - "random" - A random order for each round.

    n_imputations : int, optional (default=100)
        Number of MICE rounds to perform the results of which will be
        used in the final average.

    n_burn_in : int, optional (default=10)
        Number of initial MICE rounds to perform the results of which
        will not be returned.

    estimator : object, default=BayesianRidgeRegression
        The estimator to use at each step of the round-robin imputation.
        As of now, it must support `return_std` in its ``predict`` method.

    n_nearest_features : int, optional (default=None)
        Number of other features to use to estimate the missing values of
        the current features. Can provide significant speed-up when the number
        of features is huge. If `None`, all features will be used.

    initial_strategy : str, optional (default="mean")
        Which strategy to use to initialize the missing values. Same as the
        `strategy` option in :class:`sklearn.preprocessing.Imputer.`
        Valid values: {"mean", "median", or "most_frequent"}.

    min_value : float (default=None)
        Minimum possible imputed value.

    max_value : float (default=None)
        Maximum possible imputed value.

    verbose : boolean, optional (default=False)
        Controls the verbosity of the imputer.

    random_state : int, RandomState instance or None, optional (default=None)
        The seed of the pseudo random number generator to use when shuffling
        the data.  If int, random_state is the seed used by the random number
        generator; If RandomState instance, random_state is the random number
        generator; If None, the random number generator is the RandomState
        instance used by `np.random`.

    Notes
    -----
    Features which only contain missing values at `fit` are discarded
    upon ``transform``.

    References
    ----------
    .. [1] `Stef van Buuren, Karin Groothuis-Oudshoorn (2011). "mice:
        Multivariate Imputation by Chained Equations in R". Journal of
        Statistical Software 45: 1-67.
        <https://www.jstatsoft.org/article/view/v045i03>`_
    """

    def __init__(
            self,
            missing_values='NaN',
            imputation_order='monotone',
            n_imputations=100,
            n_burn_in=10,
            estimator=None,
            n_nearest_features=None,
            initial_strategy="mean",
            min_value=None,
            max_value=None,
            verbose=False,
            random_state=None):

        self.missing_values = missing_values
        self.imputation_order = imputation_order
        self.n_imputations = n_imputations
        self.n_burn_in = n_burn_in
        self.estimator = estimator
        self.n_nearest_features = n_nearest_features
        self.initial_strategy = initial_strategy
        self.min_value = min_value
        self.max_value = max_value
        self.verbose = verbose
        self.random_state = random_state

    def _impute_one_feature(self,
                            X_filled,
                            mask_missing_values,
                            feat_idx,
                            neighbor_feat_inds,
                            estimator=None,
                            min_std=1e-6):
        """Imputes a single feature from the others provided.

        This function predicts the missing values of one of the features using
        the current estimates of all the other features. The `estimator` must
        support `return_std=True` in its ``predict`` method for this function
        to work.

        Parameters
        ----------
        X_filled : array-like
            Input data with the most recent imputations.

        mask_missing_values : array-like
            Input data's missing indicator matrix.

        feat_idx : integer
            Index of the feature currently being imputed.

        neighbor_feat_inds : array-like
            Indices of the features to be used in imputing `feat_idx`

        estimator : object, default=BayesianRidgeRegression
            The estimator to use at this step of the round-robin imputation.
            As of now, it must support `return_std` in its ``predict`` method.
            If None, it will be fit, otherwise not.

        min_std : float, optional (default=1e-5)
            The smallest allowable standard deviation for the posterior
            sampling step.

        Returns
        -------
        X_filled : array-like
            Input data with `X_filled[missing_row_mask, feat_idx]`
            updated.

        estimator : estimator with sklearn API
            The fitted estimator used to impute
            `X_filled[missing_row_mask, feat_idx]`.
        """

        # if nothing is missing, just return the default
        rng = check_random_state(self.random_state)
        if mask_missing_values[:, feat_idx].sum() == 0:
            return X_filled, estimator
        missing_row_mask = mask_missing_values[:, feat_idx]

        # if no estimator provided, instantiate a new one and fit
        if estimator is None:
            X_train = X_filled[:, neighbor_feat_inds][~missing_row_mask]
            y_train = X_filled[:, feat_idx][~missing_row_mask]
            if np.std(y_train) > 0:
                estimator = clone(self.estimator_)
                estimator.fit(X_train, y_train)
            else:
                estimator = DummyRegressor()
                estimator.fit(X_train, y_train)

        # get posterior samples
        X_test = X_filled[:, neighbor_feat_inds][missing_row_mask]
        mus, sigmas = estimator.predict(X_test, return_std=True)
        if np.any(np.isnan(sigmas)) or np.any(np.isnan(mus)):
            print('sigmas for MICE before:', list(zip(mus, sigmas)))
            mus[np.isnan(sigmas)] = 0
            sigmas[np.isnan(sigmas)] = 0
            print('sigmas for MICE after:', list(zip(mus,sigmas)))
        imputed_values = rng.normal(
            loc=mus,
            scale=np.maximum(sigmas, min_std)
        )

        # clip the values (np.clip ignores np.nans)
        imputed_values = np.clip(imputed_values,
                                 self.min_value_,
                                 self.max_value_)

        # update the feature
        X_filled[missing_row_mask, feat_idx] = imputed_values
        return X_filled, estimator

    def _get_neighbor_feat_inds(self,
                                n_features,
                                feat_idx,
                                abs_correlation_matrix):
        """Gets a list of other features to predict `feat_idx`.

        If self.n_nearest_features is less than or equal to the total
        number of features, then use a probability proportional to the absolute
        correlation between `feat_idx` and each other feature to
        randomly choose a subsample of the other features
        (without replacement).

        Parameters
        ----------
        n_features : integer
            Number of features in `X`.

        feat_idx : integer
            Index of the feature currently being imputed.

        abs_correlation_matrix : array-like, shape (n_features, n_features)
            Absolute correlation matrix of X at the beginning of the current
            round. The diagonal has been zeroed out and each feature has been
            normalized to sum to 1.

        Returns
        -------
        neighbor_feat_inds : array-like
            The features to use to impute `feat_idx`.
        """
        if (self.n_nearest_features is not None and
                self.n_nearest_features <= n_features - 1):
            rng = check_random_state(self.random_state)
            p = abs_correlation_matrix[:, feat_idx]
            neighbor_feat_inds = rng.choice(
                np.arange(n_features),
                self.n_nearest_features,
                replace=False,
                p=p
            )
        else:
            inds_left = np.arange(feat_idx)
            inds_right = np.arange(feat_idx + 1, n_features)
            neighbor_feat_inds = np.concatenate((inds_left, inds_right))
        return neighbor_feat_inds

    def _get_ordered_inds(self, mask_missing_values):
        """Decides in what order we will update the features.

        As a homage to the MICE R package, we will have 4 main options of
        how to order the updates, and use a random order if anything else
        is specified.

        Also, this function skips features which have no missing values.

        Parameters
        ----------
        mask_missing_values : array-like, shape (n_samples, n_features)
            Input data's missing indicator matrix, where "n_samples" is the
            number of samples and "n_features" is the number of features.

        Returns
        -------
        ordered_inds : array-line, shape (n_features,)
            The order in which to impute the features.
        """
        rng = check_random_state(self.random_state)
        n_samples, n_features = mask_missing_values.shape
        fraction_of_missing_values = mask_missing_values.mean(axis=0)
        every_feat_index = np.arange(n_features)
        if self.imputation_order == 'roman':
            ordered_inds = every_feat_index
        elif self.imputation_order == 'arabic':
            ordered_inds = every_feat_index[::-1]
        elif self.imputation_order == 'monotone':
            ordered_inds = np.argsort(fraction_of_missing_values)[::-1]
        elif self.imputation_order == 'revmonotone':
            ordered_inds = np.argsort(fraction_of_missing_values)
        else:
            ordered_inds = np.arange(n_features)
            rng.shuffle(ordered_inds)

        # filter out indices for which we have no missing values
        valid_features = every_feat_index[fraction_of_missing_values > 0]
        ordered_inds = [i for i in ordered_inds if i in valid_features]
        return ordered_inds

    def _get_abs_correlation_matrix(self, X_filled, tolerance=1e-6):
        """Gets absolute correlation matrix between features.

        Parameters
        ----------
        X_filled : array-like, shape (n_samples, n_features)
            Input data with the most recent imputations.

        tolerance : float, optional (default=1e-6)
            `abs_correlation_matrix` can have nans, which will be replaced
            with `tolerance`.

        Returns
        -------
        abs_correlation_matrix : array-like, shape (n_features, n_features)
            Absolute correlation matrix of X at the beginning of the current
            round. The diagonal has been zeroed out and each feature has been
            normalized to sum to 1.
        """
        # at each stage all but one of the features is used as input
        n_features = X_filled.shape[1]
        if (self.n_nearest_features is None or
                self.n_nearest_features > n_features - 1):
            return None
        abs_correlation_matrix = np.abs(np.corrcoef(X_filled.T))
        # np.corrcoef is not defined for features with zero std
        abs_correlation_matrix[np.isnan(abs_correlation_matrix)] = tolerance
        np.fill_diagonal(abs_correlation_matrix, 0)
        abs_correlation_matrix = normalize(abs_correlation_matrix,
                                           norm='l1',
                                           axis=0)
        return abs_correlation_matrix

    def fit_transform(self, X, y=None, **fit_params):
        """Fits the imputer on X and return the transformed X.

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features)
            Input data, where "n_samples" is the number of samples and
            "n_features" is the number of features.

        Returns
        -------
        X : array-like, shape (n_samples, n_features)
            The imputed input data.
        """
        if self.estimator is None:
            from ..linear_model import BayesianRidge
            self.estimator_ = BayesianRidge()
        else:
            self.estimator_ = clone(self.estimator)

        # check that the estimator's predict method has return_std argument
        if 'return_std' not in signature(self.estimator_.predict).parameters:
            raise ValueError(
                "The regression estimator is %s and its predict method does "
                "not support 'return_std=True'. This is required for MICE." %
                type(self.estimator_)
            )

        # pre-processing of X
        X = check_array(X, dtype=np.float32, order="F", force_all_finite=False)

        # parse min and max values
        self.min_value_ = np.nan if self.min_value is None else self.min_value
        self.max_value_ = np.nan if self.max_value is None else self.max_value

        # initial imputation
        mask_missing_values = _get_mask(X, self.missing_values)
        self.initial_imputer_ = Imputer(missing_values=self.missing_values,
                                        strategy=self.initial_strategy,
                                        axis=0)
        X_filled = self.initial_imputer_.fit_transform(X)

        valid_mask = np.logical_not(np.isnan(
            self.initial_imputer_.statistics_
        ))
        self._valid_statistics_indexes = np.flatnonzero(valid_mask)
        X = X[:, self._valid_statistics_indexes]
        mask_missing_values = mask_missing_values[
                              :,
                              self._valid_statistics_indexes
        ]

        # perform imputations
        self._trained_estimator_triplets = []
        n_samples, n_features = X_filled.shape
        total_rounds = self.n_burn_in + self.n_imputations
        results_list = []
        if self.verbose:
            print("[MICE] Completing matrix with shape %s" % (X.shape,))
            start_t = time()
            mice_msg = '[MICE] Ending imputation round '
        for iter in range(total_rounds):
            # order in which to impute
            ordered_inds = self._get_ordered_inds(mask_missing_values)

            # abs_correlation matrix is used to choose a subset of other
            # features to impute from
            abs_corr_mat = self._get_abs_correlation_matrix(X_filled)

            # Fill in each feature in the order of ordered_inds
            for feat_idx in ordered_inds:
                neighbor_feat_inds = self._get_neighbor_feat_inds(
                    n_features,
                    feat_idx,
                    abs_corr_mat
                )
                X_filled, estimator = self._impute_one_feature(
                    X_filled,
                    mask_missing_values,
                    feat_idx,
                    neighbor_feat_inds
                )
                estimator_triplet = (
                    feat_idx,
                    neighbor_feat_inds,
                    estimator
                )
                self._trained_estimator_triplets.append(estimator_triplet)

            if iter >= self.n_burn_in:
                results_list.append(X_filled[mask_missing_values])
            if self.verbose:
                print(mice_msg + 'round %d/%d, elapsed time %0.2f'
                      % (iter + 1, total_rounds, time() - start_t))

        if len(results_list) > 0:
            X[mask_missing_values] = np.array(results_list).mean(axis=0)
        else:
            X[mask_missing_values] = X_filled[mask_missing_values]

        return X

    def transform(self, X):
        """Imputes all missing values in X.

        Parameters
        ----------
        X : array-like}, shape = [n_samples, n_features]
            The input data to complete.

        Returns
        -------
        X : array-like, shape (n_samples, n_features)
            The imputed input data.
        """
        check_is_fitted(self, 'initial_imputer_')
        X = check_array(X, dtype=np.float64, force_all_finite=False)
        X = np.asarray(X, order="F")
        mask_missing_values = _get_mask(X, self.missing_values)

        # initial imputation
        X_filled = self.initial_imputer_.transform(X)
        X = X[:, self._valid_statistics_indexes]
        mask_missing_values = mask_missing_values[
                              :,
                              self._valid_statistics_indexes
        ]

        # perform imputations
        n_samples, n_features = X_filled.shape
        total_rounds = self.n_burn_in + self.n_imputations
        results_list = []
        if total_rounds > 0:
            total_iterations = len(self._trained_estimator_triplets)
            imputations_per_round = total_iterations / total_rounds
            round_index = 0
            if self.verbose:
                print("[MICE] Completing matrix with shape %s" % (X.shape,))
                start_t = time()
                mice_msg = '[MICE] Ending imputation round '
            for i, estimator_triplet in \
                    enumerate(self._trained_estimator_triplets):
                feat_idx, neighbor_feat_inds, estimator = estimator_triplet
                X_filled, _ = self._impute_one_feature(X_filled,
                                                       mask_missing_values,
                                                       feat_idx,
                                                       neighbor_feat_inds,
                                                       estimator)
                if not (i + 1) % imputations_per_round:
                    round_index += 1
                    if round_index >= self.n_burn_in:
                        results_list.append(X_filled[mask_missing_values])
                    if self.verbose:
                        print(mice_msg + '%d/%d, elapsed time %0.2f'
                              % (round_index, total_rounds, time() - start_t))

        if total_rounds > 0 and len(results_list) > 0:
            X[mask_missing_values] = np.array(results_list).mean(axis=0)
        else:
            X[mask_missing_values] = X_filled[mask_missing_values]

        return X

    def fit(self, X, y=None):
        """Fits the imputer on X and return self.

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features)
            Input data, where "n_samples" is the number of samples and
            "n_features" is the number of features.

        Returns
        -------
        self : object
            Returns self.
        """
        self.fit_transform(X)
        return self
