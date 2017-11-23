
import numpy as np
from scipy import sparse

from sklearn.utils.testing import assert_equal
from sklearn.utils.testing import assert_array_equal
from sklearn.utils.testing import assert_array_almost_equal
from sklearn.utils.testing import assert_raises
from sklearn.utils.testing import assert_false

from sklearn.preprocessing.imputation import Imputer
from sklearn.preprocessing.imputation import MICEImputer
from sklearn.pipeline import Pipeline
from sklearn.model_selection import GridSearchCV
from sklearn import tree
from sklearn.random_projection import sparse_random_matrix


def _check_statistics(X, X_true,
                      strategy, statistics, missing_values):
    """Utility function for testing imputation for a given strategy.

    Test:
        - along the two axes
        - with dense and sparse arrays

    Check that:
        - the statistics (mean, median, mode) are correct
        - the missing values are imputed correctly"""

    err_msg = "Parameters: strategy = %s, missing_values = %s, " \
              "axis = {0}, sparse = {1}" % (strategy, missing_values)

    assert_ae = assert_array_equal
    if X.dtype.kind == 'f' or X_true.dtype.kind == 'f':
        assert_ae = assert_array_almost_equal

    # Normal matrix, axis = 0
    imputer = Imputer(missing_values, strategy=strategy, axis=0)
    X_trans = imputer.fit(X).transform(X.copy())
    assert_ae(imputer.statistics_, statistics,
              err_msg=err_msg.format(0, False))
    assert_ae(X_trans, X_true, err_msg=err_msg.format(0, False))

    # Normal matrix, axis = 1
    imputer = Imputer(missing_values, strategy=strategy, axis=1)
    imputer.fit(X.transpose())
    if np.isnan(statistics).any():
        assert_raises(ValueError, imputer.transform, X.copy().transpose())
    else:
        X_trans = imputer.transform(X.copy().transpose())
        assert_ae(X_trans, X_true.transpose(),
                  err_msg=err_msg.format(1, False))

    # Sparse matrix, axis = 0
    imputer = Imputer(missing_values, strategy=strategy, axis=0)
    imputer.fit(sparse.csc_matrix(X))
    X_trans = imputer.transform(sparse.csc_matrix(X.copy()))

    if sparse.issparse(X_trans):
        X_trans = X_trans.toarray()

    assert_ae(imputer.statistics_, statistics,
              err_msg=err_msg.format(0, True))
    assert_ae(X_trans, X_true, err_msg=err_msg.format(0, True))

    # Sparse matrix, axis = 1
    imputer = Imputer(missing_values, strategy=strategy, axis=1)
    imputer.fit(sparse.csc_matrix(X.transpose()))
    if np.isnan(statistics).any():
        assert_raises(ValueError, imputer.transform,
                      sparse.csc_matrix(X.copy().transpose()))
    else:
        X_trans = imputer.transform(sparse.csc_matrix(X.copy().transpose()))

        if sparse.issparse(X_trans):
            X_trans = X_trans.toarray()

        assert_ae(X_trans, X_true.transpose(),
                  err_msg=err_msg.format(1, True))


def test_imputation_shape():
    # Verify the shapes of the imputed matrix for different strategies.
    X = np.random.randn(10, 2)
    X[::2] = np.nan

    for strategy in ['mean', 'median', 'most_frequent', 'mice']:
        if strategy == 'mice':
            imputer = MICEImputer()
        else:
            imputer = Imputer(strategy=strategy)
            X_imputed = imputer.fit_transform(sparse.csr_matrix(X))
            assert_equal(X_imputed.shape, (10, 2))
        X_imputed = imputer.fit_transform(X)
        assert_equal(X_imputed.shape, (10, 2))


def test_imputation_mean_median_only_zero():
    # Test imputation using the mean and median strategies, when
    # missing_values == 0.
    X = np.array([
        [np.nan, 0, 0, 0, 5],
        [np.nan, 1, 0, np.nan, 3],
        [np.nan, 2, 0, 0, 0],
        [np.nan, 6, 0, 5, 13],
    ])

    X_imputed_mean = np.array([
        [3, 5],
        [1, 3],
        [2, 7],
        [6, 13],
    ])
    statistics_mean = [np.nan, 3, np.nan, np.nan, 7]

    # Behaviour of median with NaN is undefined, e.g. different results in
    # np.median and np.ma.median
    X_for_median = X[:, [0, 1, 2, 4]]
    X_imputed_median = np.array([
        [2, 5],
        [1, 3],
        [2, 5],
        [6, 13],
    ])
    statistics_median = [np.nan, 2, np.nan, 5]

    _check_statistics(X, X_imputed_mean, "mean", statistics_mean, 0)
    _check_statistics(X_for_median, X_imputed_median, "median",
                      statistics_median, 0)


def safe_median(arr, *args, **kwargs):
    # np.median([]) raises a TypeError for numpy >= 1.10.1
    length = arr.size if hasattr(arr, 'size') else len(arr)
    return np.nan if length == 0 else np.median(arr, *args, **kwargs)


def safe_mean(arr, *args, **kwargs):
    # np.mean([]) raises a RuntimeWarning for numpy >= 1.10.1
    length = arr.size if hasattr(arr, 'size') else len(arr)
    return np.nan if length == 0 else np.mean(arr, *args, **kwargs)


def test_imputation_mean_median():
    # Test imputation using the mean and median strategies, when
    # missing_values != 0.
    rng = np.random.RandomState(0)

    dim = 10
    dec = 10
    shape = (dim * dim, dim + dec)

    zeros = np.zeros(shape[0])
    values = np.arange(1, shape[0] + 1)
    values[4::2] = - values[4::2]

    tests = [("mean", "NaN", lambda z, v, p: safe_mean(np.hstack((z, v)))),
             ("mean", 0, lambda z, v, p: np.mean(v)),
             ("median", "NaN", lambda z, v, p: safe_median(np.hstack((z, v)))),
             ("median", 0, lambda z, v, p: np.median(v))]

    for strategy, test_missing_values, true_value_fun in tests:
        X = np.empty(shape)
        X_true = np.empty(shape)
        true_statistics = np.empty(shape[1])

        # Create a matrix X with columns
        #    - with only zeros,
        #    - with only missing values
        #    - with zeros, missing values and values
        # And a matrix X_true containing all true values
        for j in range(shape[1]):
            nb_zeros = (j - dec + 1 > 0) * (j - dec + 1) * (j - dec + 1)
            nb_missing_values = max(shape[0] + dec * dec -
                                    (j + dec) * (j + dec), 0)
            nb_values = shape[0] - nb_zeros - nb_missing_values

            z = zeros[:nb_zeros]
            p = np.repeat(test_missing_values, nb_missing_values)
            v = values[rng.permutation(len(values))[:nb_values]]

            true_statistics[j] = true_value_fun(z, v, p)

            # Create the columns
            X[:, j] = np.hstack((v, z, p))

            if 0 == test_missing_values:
                X_true[:, j] = np.hstack((v,
                                          np.repeat(
                                              true_statistics[j],
                                              nb_missing_values + nb_zeros)))
            else:
                X_true[:, j] = np.hstack((v,
                                          z,
                                          np.repeat(true_statistics[j],
                                                    nb_missing_values)))

            # Shuffle them the same way
            np.random.RandomState(j).shuffle(X[:, j])
            np.random.RandomState(j).shuffle(X_true[:, j])

        # Mean doesn't support columns containing NaNs, median does
        if strategy == "median":
            cols_to_keep = ~np.isnan(X_true).any(axis=0)
        else:
            cols_to_keep = ~np.isnan(X_true).all(axis=0)

        X_true = X_true[:, cols_to_keep]

        _check_statistics(X, X_true, strategy,
                          true_statistics, test_missing_values)


def test_imputation_median_special_cases():
    # Test median imputation with sparse boundary cases
    X = np.array([
        [0, np.nan, np.nan],  # odd: implicit zero
        [5, np.nan, np.nan],  # odd: explicit nonzero
        [0, 0, np.nan],    # even: average two zeros
        [-5, 0, np.nan],   # even: avg zero and neg
        [0, 5, np.nan],    # even: avg zero and pos
        [4, 5, np.nan],    # even: avg nonzeros
        [-4, -5, np.nan],  # even: avg negatives
        [-1, 2, np.nan],   # even: crossing neg and pos
    ]).transpose()

    X_imputed_median = np.array([
        [0, 0, 0],
        [5, 5, 5],
        [0, 0, 0],
        [-5, 0, -2.5],
        [0, 5, 2.5],
        [4, 5, 4.5],
        [-4, -5, -4.5],
        [-1, 2, .5],
    ]).transpose()
    statistics_median = [0, 5, 0, -2.5, 2.5, 4.5, -4.5, .5]

    _check_statistics(X, X_imputed_median, "median",
                      statistics_median, 'NaN')


def test_imputation_most_frequent():
    # Test imputation using the most-frequent strategy.
    X = np.array([
        [-1, -1, 0, 5],
        [-1, 2, -1, 3],
        [-1, 1, 3, -1],
        [-1, 2, 3, 7],
    ])

    X_true = np.array([
        [2, 0, 5],
        [2, 3, 3],
        [1, 3, 3],
        [2, 3, 7],
    ])

    # scipy.stats.mode, used in Imputer, doesn't return the first most
    # frequent as promised in the doc but the lowest most frequent. When this
    # test will fail after an update of scipy, Imputer will need to be updated
    # to be consistent with the new (correct) behaviour
    _check_statistics(X, X_true, "most_frequent", [np.nan, 2, 3, 3], -1)


def test_imputation_pipeline_grid_search():
    # Test imputation within a pipeline + gridsearch.
    pipeline = Pipeline([('imputer', Imputer(missing_values=0)),
                         ('tree', tree.DecisionTreeRegressor(random_state=0))])

    parameters = {
        'imputer__strategy': ["mean", "median", "most_frequent"],
        'imputer__axis': [0, 1]
    }

    n = 100
    X = sparse_random_matrix(n, n, density=0.10)
    Y = sparse_random_matrix(n, n, density=0.10).toarray()
    gs = GridSearchCV(pipeline, parameters)
    gs.fit(X, Y)


def test_mice_pipeline_grid_search():
    # Test imputation within a pipeline + gridsearch.
    pipeline = Pipeline([('imputer', MICEImputer(missing_values=0,
                                                 n_imputations=1,
                                                 n_burn_in=1,
                                                 random_state=0)),
                         ('tree', tree.DecisionTreeRegressor(random_state=0))])

    parameters = {
        'imputer__initial_strategy': ["mean", "median", "most_frequent"]
    }

    n = 100
    d = 10
    X = sparse_random_matrix(n, d, density=0.50).toarray()
    Y = np.random.random((n, d))
    gs = GridSearchCV(pipeline, parameters)
    gs.fit(X, Y)


def test_imputation_pickle():
    # Test for pickling imputers.
    import pickle

    n = 100
    X = sparse_random_matrix(n, n, density=0.10).todense()

    for strategy in ["mean", "median", "most_frequent", "mice"]:
        if strategy == 'mice':
            imputer = MICEImputer(missing_values=0, n_imputations=1,
                                  n_burn_in=1)
        else:
            imputer = Imputer(missing_values=0, strategy=strategy)
        imputer.fit(X)

        imputer_pickled = pickle.loads(pickle.dumps(imputer))

        assert_array_almost_equal(
            imputer.transform(X.copy()),
            imputer_pickled.transform(X.copy()),
            err_msg="Fail to transform the data after pickling "
            "(strategy = %s)" % (strategy)
        )


def test_imputation_copy():
    # Test imputation with copy
    X_orig = sparse_random_matrix(5, 5, density=0.75, random_state=0)

    # copy=True, dense => copy
    X = X_orig.copy().toarray()
    imputer = Imputer(missing_values=0, strategy="mean", copy=True)
    Xt = imputer.fit(X).transform(X)
    Xt[0, 0] = -1
    assert_false(np.all(X == Xt))

    # copy=True, sparse csr => copy
    X = X_orig.copy()
    imputer = Imputer(missing_values=X.data[0], strategy="mean", copy=True)
    Xt = imputer.fit(X).transform(X)
    Xt.data[0] = -1
    assert_false(np.all(X.data == Xt.data))

    # copy=False, dense => no copy
    X = X_orig.copy().toarray()
    imputer = Imputer(missing_values=0, strategy="mean", copy=False)
    Xt = imputer.fit(X).transform(X)
    Xt[0, 0] = -1
    assert_array_almost_equal(X, Xt)

    # copy=False, sparse csr, axis=1 => no copy
    X = X_orig.copy()
    imputer = Imputer(missing_values=X.data[0], strategy="mean",
                      copy=False, axis=1)
    Xt = imputer.fit(X).transform(X)
    Xt.data[0] = -1
    assert_array_almost_equal(X.data, Xt.data)

    # copy=False, sparse csc, axis=0 => no copy
    X = X_orig.copy().tocsc()
    imputer = Imputer(missing_values=X.data[0], strategy="mean",
                      copy=False, axis=0)
    Xt = imputer.fit(X).transform(X)
    Xt.data[0] = -1
    assert_array_almost_equal(X.data, Xt.data)

    # copy=False, sparse csr, axis=0 => copy
    X = X_orig.copy()
    imputer = Imputer(missing_values=X.data[0], strategy="mean",
                      copy=False, axis=0)
    Xt = imputer.fit(X).transform(X)
    Xt.data[0] = -1
    assert_false(np.all(X.data == Xt.data))

    # copy=False, sparse csc, axis=1 => copy
    X = X_orig.copy().tocsc()
    imputer = Imputer(missing_values=X.data[0], strategy="mean",
                      copy=False, axis=1)
    Xt = imputer.fit(X).transform(X)
    Xt.data[0] = -1
    assert_false(np.all(X.data == Xt.data))

    # copy=False, sparse csr, axis=1, missing_values=0 => copy
    X = X_orig.copy()
    imputer = Imputer(missing_values=0, strategy="mean",
                      copy=False, axis=1)
    Xt = imputer.fit(X).transform(X)
    assert_false(sparse.issparse(Xt))

    # Note: If X is sparse and if missing_values=0, then a (dense) copy of X is
    # made, even if copy=False.


def test_mice_rank_one():
    d = 100
    A = np.random.random((d, 1))
    B = np.random.random((1, d))
    X = np.dot(A, B)
    nan_mask = np.random.random((d, d)) < 0.5
    X_missing = X.copy()
    X_missing[nan_mask] = np.nan

    imputer = MICEImputer(n_imputations=5,
                          n_burn_in=5,
                          verbose=True)
    X_filled = imputer.fit_transform(X_missing)
    assert_array_almost_equal(X_filled, X, decimal=2)


def test_mice_imputation_order():
    n = 100
    d = 10
    X = sparse_random_matrix(n, d, density=0.10).toarray()
    X[:, 0] = 1  # this column shouldn't be ever used

    for imputation_order in ['random', 'roman', 'monotone',
                             'revmonotone', 'arabic']:
        imputer = MICEImputer(missing_values=0,
                              n_imputations=1,
                              n_burn_in=1,
                              n_nearest_features=5,
                              min_value=0,
                              max_value=1,
                              verbose=False,
                              imputation_order=imputation_order)
        imputer.fit_transform(X)
        ordered_idx = [i.feat_idx for i in imputer.imputation_sequence_]
        if imputation_order == 'roman':
            assert np.all(ordered_idx[:d-1] == np.arange(1, d))
        elif imputation_order == 'arabic':
            assert np.all(ordered_idx[:d-1] == np.arange(d-1, 0, -1))
        elif imputation_order == 'random':
            ordered_idx_round_1 = ordered_idx[:d-1]
            ordered_idx_round_2 = ordered_idx[d-1:]
            assert ordered_idx_round_1 != ordered_idx_round_2


def test_mice_predictors():
    from sklearn.dummy import DummyRegressor
    from sklearn.linear_model import BayesianRidge, ARDRegression

    n = 100
    d = 10
    X = sparse_random_matrix(n, d, density=0.10).toarray()

    for predictor in [DummyRegressor, BayesianRidge, ARDRegression]:
        imputer = MICEImputer(missing_values=0,
                              n_imputations=1,
                              n_burn_in=1,
                              predictor=predictor())
        imputer.fit_transform(X)


def test_mice_missing_at_transform():
    n = 100
    d = 10
    Xtr = np.random.randint(low=0, high=3, size=(n, d))
    Xts = np.random.randint(low=0, high=3, size=(n, d))

    Xtr[:, 0] = 1  # definitely no missing values in 0th column
    Xts[0, 0] = 0  # definitely missing value in 0th column

    for strategy in ["mean", "median", "most_frequent"]:
        mice = MICEImputer(missing_values=0,
                           n_imputations=1,
                           n_burn_in=1,
                           initial_strategy=strategy).fit(Xtr)
        initial_imputer = Imputer(missing_values=0, strategy=strategy).fit(Xtr)

        # if there were no missing values at time of fit, then mice will
        # only use the initial imputer for that feature at transform
        assert np.all(mice.transform(Xts)[:, 0] ==
                      initial_imputer.transform(Xts)[:, 0])


def test_mice_transform_correctness():
    # make data
    def make_data(rank):
        n = 100
        d = 100
        np.random.seed(0)
        A = np.random.random((n, rank))
        B = np.random.random((rank, d))
        Xfilled = np.dot(A, B)
        # half is randomly missing
        nan_mask = np.random.random((n, d)) < 0.5
        X_missing = Xfilled.copy()
        X_missing[nan_mask] = np.nan

        # split up data in half
        n = int(n/2)
        Xtr_filled = Xfilled[:n]
        Xtr = X_missing[:n]
        Xts_filled = Xfilled[n:]
        Xts = X_missing[n:]
        return Xtr_filled, Xtr, Xts_filled, Xts

    for rank in [5, 10]:
        Xtr_filled, Xtr, Xts_filled, Xts = make_data(rank)
        imputer = MICEImputer(n_imputations=10,
                              n_burn_in=10,
                              verbose=True).fit(Xtr)
        Xts_est = imputer.fit_transform(Xts)
        assert_array_almost_equal(Xts_filled, Xts_est, decimal=1)


def test_mice_additive_matrix():
        n = 100
        d = 10
        np.random.seed(0)
        A = np.random.randn(n, d)
        B = np.random.randn(n, d)
        Xfilled = np.zeros(A.shape)
        for i in range(d):
            for j in range(d):
                Xfilled[:, (i+j) % d] += (A[:, i] + B[:, j])/2
        # a quarter is randomly missing
        nan_mask = np.random.random((n, d)) < 0.25
        X_missing = Xfilled.copy()
        X_missing[nan_mask] = np.nan

        # split up data
        n = int(n/2)
        Xtr = X_missing[:n]
        Xts_filled = Xfilled[n:]
        Xts = X_missing[n:]

        imputer = MICEImputer(n_imputations=10,
                              n_burn_in=10,
                              verbose=True).fit(Xtr)
        Xts_est = imputer.fit_transform(Xts)
        assert_array_almost_equal(Xts_filled, Xts_est, decimal=2)
