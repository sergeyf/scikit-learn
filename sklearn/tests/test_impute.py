
import numpy as np
from scipy import sparse

from sklearn.utils.testing import assert_equal
from sklearn.utils.testing import assert_array_equal
from sklearn.utils.testing import assert_array_almost_equal
from sklearn.utils.testing import assert_raises
from sklearn.utils.testing import assert_false

from sklearn.impute import SimpleImputer
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

    # Normal matrix
    imputer = SimpleImputer(missing_values, strategy=strategy)
    X_trans = imputer.fit(X).transform(X.copy())
    assert_ae(imputer.statistics_, statistics,
              err_msg=err_msg.format(0, False))
    assert_ae(X_trans, X_true, err_msg=err_msg.format(0, False))

    # Sparse matrix
    imputer = SimpleImputer(missing_values, strategy=strategy)
    imputer.fit(sparse.csc_matrix(X))
    X_trans = imputer.transform(sparse.csc_matrix(X.copy()))

    if sparse.issparse(X_trans):
        X_trans = X_trans.toarray()

    assert_ae(imputer.statistics_, statistics,
              err_msg=err_msg.format(0, True))
    assert_ae(X_trans, X_true, err_msg=err_msg.format(0, True))


def test_imputation_shape():
    # Verify the shapes of the imputed matrix for different strategies.
    X = np.random.randn(10, 2)
    X[::2] = np.nan

    for strategy in ['mean', 'median', 'most_frequent']:
        imputer = SimpleImputer(strategy=strategy)
        X_imputed = imputer.fit_transform(X)
        assert_equal(X_imputed.shape, (10, 2))
        X_imputed = imputer.fit_transform(sparse.csr_matrix(X))
        assert_equal(X_imputed.shape, (10, 2))


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
            nb_missing_values = max(shape[0] + dec * dec
                                    - (j + dec) * (j + dec), 0)
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

    # scipy.stats.mode, used in SimpleImputer, doesn't return the first most
    # frequent as promised in the doc but the lowest most frequent. When this
    # test will fail after an update of scipy, SimpleImputer will need to be
    # updated to be consistent with the new (correct) behaviour
    _check_statistics(X, X_true, "most_frequent", [np.nan, 2, 3, 3], -1)


def test_imputation_pipeline_grid_search():
    # Test imputation within a pipeline + gridsearch.
    pipeline = Pipeline([('imputer', SimpleImputer(missing_values=0)),
                         ('tree', tree.DecisionTreeRegressor(random_state=0))])

    parameters = {
        'imputer__strategy': ["mean", "median", "most_frequent"]
    }

    X = sparse_random_matrix(100, 100, density=0.10)
    Y = sparse_random_matrix(100, 1, density=0.10).toarray()
    gs = GridSearchCV(pipeline, parameters)
    gs.fit(X, Y)


def test_imputation_copy():
    # Test imputation with copy
    X_orig = sparse_random_matrix(5, 5, density=0.75, random_state=0)

    # copy=True, dense => copy
    X = X_orig.copy().toarray()
    imputer = SimpleImputer(missing_values=0, strategy="mean", copy=True)
    Xt = imputer.fit(X).transform(X)
    Xt[0, 0] = -1
    assert_false(np.all(X == Xt))

    # copy=True, sparse csr => copy
    X = X_orig.copy()
    imputer = SimpleImputer(missing_values=X.data[0], strategy="mean",
                            copy=True)
    Xt = imputer.fit(X).transform(X)
    Xt.data[0] = -1
    assert_false(np.all(X.data == Xt.data))

    # copy=False, dense => no copy
    X = X_orig.copy().toarray()
    imputer = SimpleImputer(missing_values=0, strategy="mean", copy=False)
    Xt = imputer.fit(X).transform(X)
    Xt[0, 0] = -1
    assert_array_almost_equal(X, Xt)

    # copy=False, sparse csc => no copy
    X = X_orig.copy().tocsc()
    imputer = SimpleImputer(missing_values=X.data[0], strategy="mean",
                            copy=False)
    Xt = imputer.fit(X).transform(X)
    Xt.data[0] = -1
    assert_array_almost_equal(X.data, Xt.data)

    # copy=False, sparse csr => copy
    X = X_orig.copy()
    imputer = SimpleImputer(missing_values=X.data[0], strategy="mean",
                            copy=False)
    Xt = imputer.fit(X).transform(X)
    Xt.data[0] = -1
    assert_false(np.all(X.data == Xt.data))
