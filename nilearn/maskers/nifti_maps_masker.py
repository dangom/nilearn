"""Transformer for computing ROI signals."""

import warnings
from copy import deepcopy

import numpy as np
from sklearn.utils.estimator_checks import check_is_fitted

from nilearn._utils.class_inspect import get_params
from nilearn._utils.docs import fill_doc
from nilearn._utils.helpers import is_matplotlib_installed
from nilearn._utils.logger import find_stack_level
from nilearn._utils.niimg_conversions import check_niimg, check_same_fov
from nilearn._utils.param_validation import check_params
from nilearn.image import clean_img, get_data, index_img, resample_img
from nilearn.maskers._utils import compute_middle_image
from nilearn.maskers.base_masker import (
    BaseMasker,
    filter_and_extract,
    mask_logger,
)
from nilearn.masking import load_mask_img


class _ExtractionFunctor:
    func_name = "nifti_maps_masker_extractor"

    def __init__(self, maps_img_, mask_img_, keep_masked_maps):
        self.maps_img_ = maps_img_
        self.mask_img_ = mask_img_
        self.keep_masked_maps = keep_masked_maps

    def __call__(self, imgs):
        from ..regions import signal_extraction

        return signal_extraction.img_to_signals_maps(
            imgs,
            self.maps_img_,
            mask_img=self.mask_img_,
            keep_masked_maps=self.keep_masked_maps,
        )


@fill_doc
class NiftiMapsMasker(BaseMasker):
    """Class for extracting data from Niimg-like objects \
       using maps of potentially overlapping brain regions.

    NiftiMapsMasker is useful when data from overlapping volumes should be
    extracted (contrarily to :class:`nilearn.maskers.NiftiLabelsMasker`).

    Use case:
    summarize brain signals from large-scale networks
    obtained by prior PCA or :term:`ICA`.

    .. note::
        Inf or NaN present in the given input images are automatically
        put to zero rather than considered as missing data.

    For more details on the definitions of maps in Nilearn,
    see the :ref:`region` section.

    Parameters
    ----------
    maps_img : 4D niimg-like object or None, default=None
        See :ref:`extracting_data`.
        Set of continuous maps. One representative time course per map is
        extracted using least square regression.

    mask_img : 3D niimg-like object, optional
        See :ref:`extracting_data`.
        Mask to apply to regions before extracting signals.

    allow_overlap : :obj:`bool`, default=True
        If False, an error is raised if the maps overlaps (ie at least two
        maps have a non-zero value for the same voxel).

    %(smoothing_fwhm)s

    %(standardize_maskers)s

    %(standardize_confounds)s

    high_variance_confounds : :obj:`bool`, default=False
        If True, high variance confounds are computed on provided image with
        :func:`nilearn.image.high_variance_confounds` and default parameters
        and regressed out.

    %(detrend)s

    %(low_pass)s

    %(high_pass)s

    %(t_r)s

    %(dtype)s.

    resampling_target : {"data", "mask", "maps", None}, default="data"
        Gives which image gives the final shape/size. For example, if
        `resampling_target` is "mask" then maps_img and images provided to
        fit() are resampled to the shape and affine of mask_img. "None" means
        no resampling: if shapes and affines do not match, a ValueError is
        raised.

    %(memory)s

    %(memory_level)s

    %(verbose0)s

    %(keep_masked_maps)s

    reports : :obj:`bool`, default=True
        If set to True, data is saved in order to produce a report.

    %(cmap)s
        default="CMRmap_r"
        Only relevant for the report figures.

    %(clean_args)s
        .. versionadded:: 0.12.0

    %(masker_kwargs)s

    Attributes
    ----------
    maps_img_ : :obj:`nibabel.nifti1.Nifti1Image`
        The maps mask of the data.

    %(nifti_mask_img_)s

    n_elements_ : :obj:`int`
        The number of overlapping maps in the mask.
        This is equivalent to the number of volumes in the mask image.

        .. versionadded:: 0.9.2

    Notes
    -----
    If resampling_target is set to "maps", every 3D image processed by
    transform() will be resampled to the shape of maps_img. It may lead to a
    very large memory consumption if the voxel number in maps_img is large.

    See Also
    --------
    nilearn.maskers.NiftiMasker
    nilearn.maskers.NiftiLabelsMasker

    """

    # memory and memory_level are used by CacheMixin.

    def __init__(
        self,
        maps_img=None,
        mask_img=None,
        allow_overlap=True,
        smoothing_fwhm=None,
        standardize=False,
        standardize_confounds=True,
        high_variance_confounds=False,
        detrend=False,
        low_pass=None,
        high_pass=None,
        t_r=None,
        dtype=None,
        resampling_target="data",
        keep_masked_maps=True,
        memory=None,
        memory_level=0,
        verbose=0,
        reports=True,
        cmap="CMRmap_r",
        clean_args=None,
        **kwargs,  # TODO remove when bumping to nilearn >0.13
    ):
        self.maps_img = maps_img
        self.mask_img = mask_img

        # Maps Masker parameter
        self.allow_overlap = allow_overlap

        # Parameters for image.smooth
        self.smoothing_fwhm = smoothing_fwhm

        # Parameters for clean()
        self.standardize = standardize
        self.standardize_confounds = standardize_confounds
        self.high_variance_confounds = high_variance_confounds
        self.detrend = detrend
        self.low_pass = low_pass
        self.high_pass = high_pass
        self.t_r = t_r
        self.dtype = dtype
        self.clean_args = clean_args

        # TODO remove when bumping to nilearn >0.13
        self.clean_kwargs = kwargs

        # Parameters for resampling
        self.resampling_target = resampling_target

        # Parameters for joblib
        self.memory = memory
        self.memory_level = memory_level
        self.verbose = verbose

        self.reports = reports
        self.cmap = cmap

        self.keep_masked_maps = keep_masked_maps

    def generate_report(self, displayed_maps=10):
        """Generate an HTML report for the current ``NiftiMapsMasker`` object.

        .. note::
            This functionality requires to have ``Matplotlib`` installed.

        Parameters
        ----------
        displayed_maps : :obj:`int`, or :obj:`list`, \
                         or :class:`~numpy.ndarray`, or "all", default=10
            Indicates which maps will be displayed in the HTML report.

                - If "all": All maps will be displayed in the report.

                .. code-block:: python

                    masker.generate_report("all")

                .. warning:
                    If there are too many maps, this might be time and
                    memory consuming, and will result in very heavy
                    reports.

                - If a :obj:`list` or :class:`~numpy.ndarray`: This indicates
                  the indices of the maps to be displayed in the report. For
                  example, the following code will generate a report with maps
                  6, 3, and 12, displayed in this specific order:

                .. code-block:: python

                    masker.generate_report([6, 3, 12])

                - If an :obj:`int`: This will only display the first n maps,
                  n being the value of the parameter. By default, the report
                  will only contain the first 10 maps. Example to display the
                  first 16 maps:

                .. code-block:: python

                    masker.generate_report(16)

        Returns
        -------
        report : `nilearn.reporting.html_report.HTMLReport`
            HTML report for the masker.
        """
        from nilearn.reporting.html_report import generate_report

        if not is_matplotlib_installed():
            return generate_report(self)

        incorrect_type = not isinstance(
            displayed_maps, (list, np.ndarray, int, str)
        )
        incorrect_string = (
            isinstance(displayed_maps, str) and displayed_maps != "all"
        )
        not_integer = (
            not isinstance(displayed_maps, str)
            and np.array(displayed_maps).dtype != int
        )
        if incorrect_type or incorrect_string or not_integer:
            raise TypeError(
                "Parameter ``displayed_maps`` of "
                "``generate_report()`` should be either 'all' or "
                "an int, or a list/array of ints. You provided a "
                f"{type(displayed_maps)}"
            )
        self.displayed_maps = displayed_maps

        return generate_report(self)

    def _reporting(self):
        """Return a list of all displays to be rendered.

        Returns
        -------
        displays : list
            A list of all displays to be rendered.

        """
        from nilearn import plotting
        from nilearn.reporting.html_report import embed_img

        if self._reporting_data is not None:
            maps_image = self._reporting_data["maps_image"]
        else:
            maps_image = None

        if maps_image is None:
            return [None]

        n_maps = get_data(maps_image).shape[-1]

        maps_to_be_displayed = range(n_maps)
        if isinstance(self.displayed_maps, int):
            if n_maps < self.displayed_maps:
                msg = (
                    "`generate_report()` received "
                    f"{self.displayed_maps} to be displayed. "
                    f"But masker only has {n_maps} maps. "
                    f"Setting number of displayed maps to {n_maps}."
                )
                warnings.warn(
                    category=UserWarning,
                    message=msg,
                    stacklevel=find_stack_level(),
                )
                self.displayed_maps = n_maps
            maps_to_be_displayed = range(self.displayed_maps)

        elif isinstance(self.displayed_maps, (list, np.ndarray)):
            if max(self.displayed_maps) > n_maps:
                raise ValueError(
                    "Report cannot display the following maps "
                    f"{self.displayed_maps} because "
                    f"masker only has {n_maps} maps."
                )
            maps_to_be_displayed = self.displayed_maps

        self._report_content["number_of_maps"] = n_maps
        self._report_content["displayed_maps"] = list(maps_to_be_displayed)

        img = self._reporting_data["img"]
        embedded_images = []

        if img is None:
            msg = (
                "No image provided to fit in NiftiMapsMasker. "
                "Plotting only spatial maps for reporting."
            )
            warnings.warn(msg, stacklevel=find_stack_level())
            self._report_content["warning_message"] = msg
            for component in maps_to_be_displayed:
                display = plotting.plot_stat_map(
                    index_img(maps_image, component)
                )
                embedded_images.append(embed_img(display))
                display.close()
            return embedded_images

        if self._reporting_data["dim"] == 5:
            msg = (
                "A list of 4D subject images were provided to fit. "
                "Only first subject is shown in the report."
            )
            warnings.warn(msg, stacklevel=find_stack_level())
            self._report_content["warning_message"] = msg

        for component in maps_to_be_displayed:
            # Find the cut coordinates
            cut_coords = plotting.find_xyz_cut_coords(
                index_img(maps_image, component)
            )
            display = plotting.plot_img(
                img,
                cut_coords=cut_coords,
                black_bg=False,
                cmap=self.cmap,
            )
            display.add_overlay(
                index_img(maps_image, component),
                cmap=plotting.cm.black_blue,
            )
            embedded_images.append(embed_img(display))
            display.close()
        return embedded_images

    @fill_doc
    def fit(self, imgs=None, y=None):
        """Prepare signal extraction from regions.

        Parameters
        ----------
        imgs : :obj:`list` of Niimg-like objects or None, default=None
            See :ref:`extracting_data`.
            Image data passed to the reporter.

        %(y_dummy)s
        """
        del y
        check_params(self.__dict__)
        if self.resampling_target not in ("mask", "maps", "data", None):
            raise ValueError(
                "invalid value for 'resampling_target' "
                f"parameter: {self.resampling_target}"
            )

        if self.mask_img is None and self.resampling_target == "mask":
            raise ValueError(
                "resampling_target has been set to 'mask' but no mask "
                "has been provided.\n"
                "Set resampling_target to something else or provide a mask."
            )

        self._sanitize_cleaning_parameters()
        self.clean_args_ = {} if self.clean_args is None else self.clean_args

        self._report_content = {
            "description": (
                "This reports shows the spatial maps provided to the mask."
            ),
            "warning_message": None,
        }

        # Load images
        maps_img = self.maps_img
        if hasattr(self, "_maps_img"):
            # This is for RegionExtractor that first modifies
            # maps_img before passing to its parent fit method.
            maps_img = self._maps_img

        mask_logger("load_regions", maps_img, verbose=self.verbose)

        self.maps_img_ = deepcopy(maps_img)
        self.maps_img_ = check_niimg(
            self.maps_img_, dtype=self.dtype, atleast_4d=True
        )
        self.maps_img_ = clean_img(
            self.maps_img_,
            detrend=False,
            standardize=False,
            ensure_finite=True,
        )

        if imgs is not None:
            imgs_ = check_niimg(imgs)

        self.mask_img_ = self._load_mask(imgs)

        # Check shapes and affines for resample.
        if self.resampling_target is None:
            images = {"maps": self.maps_img_}
            if self.mask_img_ is not None:
                images["mask"] = self.mask_img_
            if imgs is not None:
                images["data"] = imgs_
            check_same_fov(raise_error=True, **images)

        ref_img = None
        if self.resampling_target == "data" and imgs is not None:
            ref_img = imgs_
        elif self.resampling_target == "mask":
            ref_img = self.mask_img_
        elif self.resampling_target == "maps":
            ref_img = self.maps_img_

        if ref_img is not None:
            if self.resampling_target != "maps" and not check_same_fov(
                ref_img, self.maps_img_
            ):
                mask_logger("resample_regions", verbose=self.verbose)

                # TODO switch to force_resample=True
                # when bumping to version > 0.13
                self.maps_img_ = self._cache(resample_img)(
                    self.maps_img_,
                    interpolation="linear",
                    target_shape=ref_img.shape[:3],
                    target_affine=ref_img.affine,
                    copy_header=True,
                    force_resample=False,
                )
            if self.mask_img_ is not None and not check_same_fov(
                ref_img, self.mask_img_
            ):
                mask_logger("resample_mask", verbose=self.verbose)

                # TODO switch to force_resample=True
                # when bumping to version > 0.13
                self.mask_img_ = resample_img(
                    self.mask_img_,
                    target_affine=ref_img.affine,
                    target_shape=ref_img.shape[:3],
                    interpolation="nearest",
                    copy=True,
                    copy_header=True,
                    force_resample=False,
                )

                # Just check that the mask is valid
                load_mask_img(self.mask_img_)

        if self.reports:
            self._reporting_data = {
                "maps_image": self.maps_img_,
                "mask": self.mask_img_,
                "dim": None,
                "img": imgs,
            }
            if imgs is not None:
                imgs, dims = compute_middle_image(imgs)
                self._reporting_data["img"] = imgs
                self._reporting_data["dim"] = dims
        else:
            self._reporting_data = None

        # The number of elements is equal to the number of volumes
        self.n_elements_ = self.maps_img_.shape[3]

        mask_logger("fit_done", verbose=self.verbose)

        return self

    def __sklearn_is_fitted__(self):
        return hasattr(self, "maps_img_") and hasattr(self, "n_elements_")

    @fill_doc
    def fit_transform(self, imgs, y=None, confounds=None, sample_mask=None):
        """Prepare and perform signal extraction.

        Parameters
        ----------
        imgs : 3D/4D Niimg-like object
            See :ref:`extracting_data`.
            Images to process.
            If a 3D niimg is provided, a 1D array is returned.

        %(y_dummy)s

        %(confounds)s

        %(sample_mask)s

                .. versionadded:: 0.8.0

        Returns
        -------
        %(signals_transform_nifti)s
        """
        del y
        return self.fit(imgs).transform(
            imgs, confounds=confounds, sample_mask=sample_mask
        )

    @fill_doc
    def transform_single_imgs(self, imgs, confounds=None, sample_mask=None):
        """Extract signals from a single 4D niimg.

        Parameters
        ----------
        imgs : 3D/4D Niimg-like object
            See :ref:`extracting_data`.
            Images to process.

        confounds : CSV file or array-like, default=None
            This parameter is passed to :func:`nilearn.signal.clean`.
            Please see the related documentation for details.
            shape: (number of scans, number of confounds)

        %(sample_mask)s

                .. versionadded:: 0.8.0

        Returns
        -------
        %(signals_transform_nifti)s

        """
        check_is_fitted(self)

        # imgs passed at transform time may be different
        # from those passed at fit time.
        # So it may be needed to resample mask and maps,
        # if 'data' is the resampling target.
        # We handle the resampling of maps and mask separately because the
        # affine of the maps and mask images should not impact the extraction
        # of the signal.
        #
        # Any resampling of the mask or maps is not 'kept' after transform,
        # to avoid modifying the masker after fit.
        #
        # If the resampling target is different,
        # then resampling was already done at fit time
        # (e.g resampling of the mask image to the maps image
        # if the target was 'maps'),
        # or resampling of the data will be done at extract time.

        mask_img_ = self.mask_img_
        maps_img_ = self.maps_img_

        imgs_ = check_niimg(imgs, atleast_4d=True)

        if self.resampling_target is None:
            images = {"maps": maps_img_, "data": imgs_}
            if mask_img_ is not None:
                images["mask"] = mask_img_
            check_same_fov(raise_error=True, **images)
        elif self.resampling_target == "data":
            ref_img = imgs_

            if not check_same_fov(ref_img, maps_img_):
                warnings.warn(
                    (
                        "Resampling maps at transform time...\n"
                        "To avoid this warning, make sure to pass the images "
                        "you want to transform to fit() first, "
                        "or directly use fit_transform()."
                    ),
                    stacklevel=find_stack_level(),
                )
                # TODO switch to force_resample=True
                # when bumping to version > 0.13
                maps_img_ = self._cache(resample_img)(
                    self.maps_img_,
                    interpolation="linear",
                    target_shape=ref_img.shape[:3],
                    target_affine=ref_img.affine,
                    copy_header=True,
                    force_resample=False,
                )

            if self.mask_img_ is not None and not check_same_fov(
                ref_img,
                self.mask_img_,
            ):
                warnings.warn(
                    (
                        "Resampling mask at transform time...\n"
                        "To avoid this warning, make sure to pass the images "
                        "you want to transform to fit() first, "
                        "or directly use fit_transform()."
                    ),
                    stacklevel=find_stack_level(),
                )
                # TODO switch to force_resample=True
                # when bumping to version > 0.13
                mask_img_ = self._cache(resample_img)(
                    self.mask_img_,
                    interpolation="nearest",
                    target_shape=ref_img.shape[:3],
                    target_affine=ref_img.affine,
                    copy_header=True,
                    force_resample=False,
                )

            # Remove imgs_ from memory before loading the same image
            # in filter_and_extract.
            del imgs_

        if not self.allow_overlap:
            # Check if there is an overlap.

            # If float, we set low values to 0
            data = get_data(maps_img_)
            dtype = data.dtype
            if dtype.kind == "f":
                data[data < np.finfo(dtype).eps] = 0.0

            # Check the overlaps
            if np.any(np.sum(data > 0.0, axis=3) > 1):
                raise ValueError(
                    "Overlap detected in the maps. The overlap may be "
                    "due to the atlas itself or possibly introduced by "
                    "resampling."
                )

        target_shape = None
        target_affine = None
        if self.resampling_target != "data":
            target_shape = maps_img_.shape[:3]
            target_affine = maps_img_.affine

        params = get_params(
            NiftiMapsMasker,
            self,
            ignore=["resampling_target"],
        )
        params["target_shape"] = target_shape
        params["target_affine"] = target_affine
        params["clean_kwargs"] = self.clean_args_
        # TODO remove in 0.13.0
        if self.clean_kwargs:
            params["clean_kwargs"] = self.clean_kwargs_

        region_signals, _ = self._cache(
            filter_and_extract,
            ignore=["verbose", "memory", "memory_level"],
        )(
            # Images
            imgs,
            _ExtractionFunctor(
                maps_img_,
                mask_img_,
                self.keep_masked_maps,
            ),
            # Pre-treatments
            params,
            confounds=confounds,
            sample_mask=sample_mask,
            dtype=self.dtype,
            # Caching
            memory=self.memory,
            memory_level=self.memory_level,
            # kwargs
            verbose=self.verbose,
        )
        return region_signals

    @fill_doc
    def inverse_transform(self, region_signals):
        """Compute :term:`voxel` signals from region signals.

        Any mask given at initialization is taken into account.

        Parameters
        ----------
        %(region_signals_inv_transform)s

        Returns
        -------
        %(img_inv_transform_nifti)s

        """
        from ..regions import signal_extraction

        check_is_fitted(self)

        region_signals = self._check_array(region_signals)

        mask_logger("inverse_transform", verbose=self.verbose)

        return signal_extraction.signals_to_img_maps(
            region_signals,
            self.maps_img_,
            mask_img=self.mask_img_,
        )
