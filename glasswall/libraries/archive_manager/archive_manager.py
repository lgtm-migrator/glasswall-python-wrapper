

import ctypes as ct
import functools
import io
import logging
import os
from typing import Union

import glasswall
from glasswall import utils
from glasswall.config.logging import log
from glasswall.libraries.archive_manager import errors, successes
from glasswall.libraries.library import Library


class ArchiveManager(Library):
    """ A high level Python wrapper for Glasswall Archive Manager. """
    class Decorators:
        @classmethod
        def release_after(cls, function):
            """ Call function followed by self.release() """
            @functools.wraps(function)
            def wrapper(self, *args, **kwargs):
                result = function(self, *args, **kwargs)
                self.release()
                return result
            return wrapper

    def __init__(self, library_path):
        super().__init__(library_path)
        self.library = self.load_library(os.path.abspath(library_path))

        log.info(f"Loaded Glasswall {self.__class__.__name__} version {self.version()} from {self.library_path}")

    def version(self):
        """ Returns the Glasswall library version.

        Returns:
            version (str): The Glasswall library version.
        """
        # API function declaration
        self.library.GwArchiveVersion.restype = ct.c_char_p

        # API call
        version = self.library.GwArchiveVersion()

        # Convert to Python string
        version = ct.string_at(version).decode()

        return version

    def release(self):
        """ Releases any resources held by the Glasswall Archive Manager library. """
        self.library.GwArchiveDone()

    @Decorators.release_after
    def analyse_archive(self, input_file: Union[str, bytes, bytearray, io.BytesIO], output_file: Union[None, str] = None, output_report: Union[None, str] = None, content_management_policy: Union[type(None), str, bytes, bytearray, io.BytesIO] = None, raise_unsupported: bool = True):
        """ Extracts the input_file archive and processes each file within the archive using the Glasswall engine. Repackages all files regenerated by the Glasswall engine into a new archive, optionally writing the new archive and report to the paths specified by output_file and output_report.

        Args:
            input_file (Union[str, bytes, bytearray, io.BytesIO]): The archive file path or bytes.
            output_file (Union[None, str], optional): Default None. If str, write the new archive to the output_file path.
            output_report (Union[None, str], optional): Default None. If str, write a report to the output_file path.
            content_management_policy (Union[str, bytes, bytearray, io.BytesIO)], optional): The content_management_policy file path or bytes.
            raise_unsupported (bool, optional): Default True. Raise exceptions when Glasswall encounters an error. Fail silently if False.

        Returns:
            gw_return_object (glasswall.GwReturnObj): An instance of class glasswall.GwReturnObj containing attributes: "status" (int), "output_file" (bytes), "output_report" (bytes)
        """
        # Validate arg types
        if not isinstance(input_file, (str, bytes, bytearray, io.BytesIO)):
            raise TypeError(input_file)
        if not isinstance(output_file, (type(None), str)):
            raise TypeError(output_file)
        if not isinstance(output_report, (type(None), str)):
            raise TypeError(output_report)
        if not isinstance(content_management_policy, (type(None), str, bytes, bytearray, io.BytesIO, glasswall.content_management.policies.Policy)):
            raise TypeError(content_management_policy)

        # Convert string path arguments to absolute paths
        if isinstance(output_file, str):
            output_file = os.path.abspath(output_file)

        if isinstance(output_report, str):
            output_report = os.path.abspath(output_report)

        # Convert inputs to bytes
        if isinstance(input_file, str):
            if not os.path.isfile(input_file):
                raise FileNotFoundError(input_file)
            with open(input_file, "rb") as f:
                input_file_bytes = f.read()
        elif isinstance(input_file, (bytearray, io.BytesIO)):
            input_file_bytes = utils.as_bytes(input_file)

        if isinstance(content_management_policy, str) and os.path.isfile(content_management_policy):
            with open(content_management_policy, "rb") as f:
                content_management_policy = f.read()
        elif isinstance(content_management_policy, type(None)):
            # Load default
            content_management_policy = glasswall.content_management.policies.ArchiveManager(default="sanitise", default_archive_manager="process")
        content_management_policy = utils.validate_xml(content_management_policy)

        # API function declaration
        self.library.GwFileAnalysisArchive.argtypes = [
            ct.c_void_p,
            ct.c_size_t,
            ct.POINTER(ct.c_void_p),
            ct.POINTER(ct.c_size_t),
            ct.POINTER(ct.c_void_p),
            ct.POINTER(ct.c_size_t),
            ct.c_char_p
        ]

        # Variable initialisation
        input_buffer_bytearray = bytearray(input_file_bytes)

        ct_input_buffer = (ct.c_ubyte * len(input_buffer_bytearray)).from_buffer(input_buffer_bytearray)  # void *inputBuffer
        ct_input_buffer_length = ct.c_size_t(len(input_file_bytes))  # size_t inputBufferLength
        ct_output_buffer = ct.c_void_p()  # void **outputFileBuffer
        ct_output_buffer_length = ct.c_size_t()  # size_t *outputFileBufferLength
        ct_output_report_buffer = ct.c_void_p()  # void **outputAnalysisReportBuffer
        ct_output_report_buffer_length = ct.c_size_t()  # size_t *outputAnalysisReportBufferLength
        ct_content_management_policy = ct.c_char_p(content_management_policy.encode())  # const char *xmlConfigString
        gw_return_object = glasswall.GwReturnObj()

        with utils.CwdHandler(new_cwd=self.library_path):
            # API call
            gw_return_object.status = self.library.GwFileAnalysisArchive(
                ct.byref(ct_input_buffer),
                ct_input_buffer_length,
                ct.byref(ct_output_buffer),
                ct.byref(ct_output_buffer_length),
                ct.byref(ct_output_report_buffer),
                ct.byref(ct_output_report_buffer_length),
                ct_content_management_policy
            )

        if gw_return_object.status not in successes.success_codes:
            if raise_unsupported:
                raise errors.error_codes.get(gw_return_object.status, errors.UnknownErrorCode)(gw_return_object.status)

        gw_return_object.output_file = utils.buffer_to_bytes(
            ct_output_buffer,
            ct_output_buffer_length
        )
        gw_return_object.output_report = utils.buffer_to_bytes(
            ct_output_report_buffer,
            ct_output_report_buffer_length
        )

        # Write output file
        if gw_return_object.output_file:
            if isinstance(output_file, str):
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                with open(output_file, "wb") as f:
                    f.write(gw_return_object.output_file)

        # Write output report
        if gw_return_object.output_report:
            if isinstance(output_report, str):
                os.makedirs(os.path.dirname(output_report), exist_ok=True)
                with open(output_report, "wb") as f:
                    f.write(gw_return_object.output_report)

        return gw_return_object

    def analyse_directory(self, input_directory: str, output_directory: str, content_management_policy: Union[None, str, bytes, bytearray, io.BytesIO] = None, raise_unsupported: bool = True):
        """ Calls analyse_archive on each file in input_directory using the given content management configuration. The resulting archives and analysis reports are written to output_directory maintaining the same directory structure as input_directory.

        Args:
            input_directory (str): The input directory containing archives to analyse.
            output_directory (str): The output directory where the new archives and reports will be written.
            content_management_policy (Union[None, str, bytes, bytearray, io.BytesIO], optional): The content management policy .xml to use.
            raise_unsupported (bool, optional): Default True. Raise exceptions when Glasswall encounters an error. Fail silently if False.

        Returns:
            None
        """
        for relative_path in utils.list_file_paths(input_directory, absolute=False):
            # construct absolute paths
            input_file = os.path.abspath(os.path.join(input_directory, relative_path))
            output_file = os.path.abspath(os.path.join(output_directory, relative_path))

            # call analyse_archive on each file in input_directory
            self.analyse_archive(
                input_file=input_file,
                output_file=output_file,
                output_report=output_file + ".xml",
                content_management_policy=content_management_policy,
                raise_unsupported=raise_unsupported,
            )

    @Decorators.release_after
    def protect_archive(self, input_file: Union[str, bytes, bytearray, io.BytesIO], output_file: Union[None, str] = None, output_report: Union[None, str] = None, content_management_policy: Union[type(None), str, bytes, bytearray, io.BytesIO] = None, raise_unsupported: bool = True):
        """ Extracts the input_file archive and processes each file within the archive using the Glasswall engine. Repackages all files regenerated by the Glasswall engine into a new archive, optionally writing the new archive and report to the paths specified by output_file and output_report.

        Args:
            input_file (Union[str, bytes, bytearray, io.BytesIO]): The archive file path or bytes.
            output_file (Union[None, str], optional): Default None. If str, write the new archive to the output_file path.
            output_report (Union[None, str], optional): Default None. If str, write a report to the output_file path.
            content_management_policy (Union[str, bytes, bytearray, io.BytesIO, glasswall.content_management.policies.Policy)], optional): The content_management_policy file path or bytes.
            raise_unsupported (bool, optional): Default True. Raise exceptions when Glasswall encounters an error. Fail silently if False.

        Returns:
            gw_return_object (glasswall.GwReturnObj): An instance of class glasswall.GwReturnObj containing attributes: "status" (int), "output_file" (bytes), "output_report" (bytes)
        """
        # Validate arg types
        if not isinstance(input_file, (str, bytes, bytearray, io.BytesIO)):
            raise TypeError(input_file)
        if not isinstance(output_file, (type(None), str)):
            raise TypeError(output_file)
        if not isinstance(output_report, (type(None), str)):
            raise TypeError(output_report)
        if not isinstance(content_management_policy, (type(None), str, bytes, bytearray, io.BytesIO, glasswall.content_management.policies.Policy)):
            raise TypeError(content_management_policy)

        # Convert string path arguments to absolute paths
        if isinstance(output_file, str):
            output_file = os.path.abspath(output_file)

        if isinstance(output_report, str):
            output_report = os.path.abspath(output_report)

        # Convert inputs to bytes
        if isinstance(input_file, str):
            if not os.path.isfile(input_file):
                raise FileNotFoundError(input_file)
            with open(input_file, "rb") as f:
                input_file_bytes = f.read()
        elif isinstance(input_file, (bytearray, io.BytesIO)):
            input_file_bytes = utils.as_bytes(input_file)

        if isinstance(content_management_policy, str) and os.path.isfile(content_management_policy):
            with open(content_management_policy, "rb") as f:
                content_management_policy = f.read()
        elif isinstance(content_management_policy, type(None)):
            # Load default
            content_management_policy = glasswall.content_management.policies.ArchiveManager(default="sanitise", default_archive_manager="process")
        content_management_policy = utils.validate_xml(content_management_policy)

        # API function declaration
        self.library.GwFileAnalysisArchive.argtypes = [
            ct.c_void_p,
            ct.c_size_t,
            ct.POINTER(ct.c_void_p),
            ct.POINTER(ct.c_size_t),
            ct.POINTER(ct.c_void_p),
            ct.POINTER(ct.c_size_t),
            ct.c_char_p
        ]

        # Variable initialisation
        input_buffer_bytearray = bytearray(input_file_bytes)

        ct_input_buffer = (ct.c_ubyte * len(input_buffer_bytearray)).from_buffer(input_buffer_bytearray)  # void *inputBuffer
        ct_input_buffer_length = ct.c_size_t(len(input_file_bytes))  # size_t inputBufferLength
        ct_output_buffer = ct.c_void_p()  # void **outputFileBuffer
        ct_output_buffer_length = ct.c_size_t()  # size_t *outputFileBufferLength
        ct_output_report_buffer = ct.c_void_p()  # void **outputAnalysisReportBuffer
        ct_output_report_buffer_length = ct.c_size_t()  # size_t *outputAnalysisReportBufferLength
        ct_content_management_policy = ct.c_char_p(content_management_policy.encode())  # const char *xmlConfigString
        gw_return_object = glasswall.GwReturnObj()

        with utils.CwdHandler(new_cwd=self.library_path):
            # API call
            gw_return_object.status = self.library.GwFileProtectAndReportArchive(
                ct.byref(ct_input_buffer),
                ct_input_buffer_length,
                ct.byref(ct_output_buffer),
                ct.byref(ct_output_buffer_length),
                ct.byref(ct_output_report_buffer),
                ct.byref(ct_output_report_buffer_length),
                ct_content_management_policy
            )

        if gw_return_object.status not in successes.success_codes:
            if raise_unsupported:
                raise errors.error_codes.get(gw_return_object.status, errors.UnknownErrorCode)(gw_return_object.status)

        gw_return_object.output_file = utils.buffer_to_bytes(
            ct_output_buffer,
            ct_output_buffer_length
        )
        gw_return_object.output_report = utils.buffer_to_bytes(
            ct_output_report_buffer,
            ct_output_report_buffer_length
        )

        # Write output file
        if gw_return_object.output_file:
            if isinstance(output_file, str):
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                with open(output_file, "wb") as f:
                    f.write(gw_return_object.output_file)

        # Write output report
        if gw_return_object.output_report:
            if isinstance(output_report, str):
                os.makedirs(os.path.dirname(output_report), exist_ok=True)
                with open(output_report, "wb") as f:
                    f.write(gw_return_object.output_report)

        return gw_return_object

    def protect_directory(self, input_directory: str, output_directory: Union[None, str], output_report_directory: Union[None, str] = None, content_management_policy: Union[None, str, bytes, bytearray, io.BytesIO] = None, raise_unsupported: bool = True):
        """ Calls protect_archive on each file in input_directory using the given content management configuration. The resulting archives are written to output_directory maintaining the same directory structure as input_directory.

        Args:
            input_directory (str): The input directory containing archives to protect.
            output_directory (Union[None, str], optional): Default None. If str, the output directory where the new archives will be written.
            output_report_directory (Union[None, str], optional): Default None. If str, the output directory where xml reports for each archive will be written.
            content_management_policy (Union[None, str, bytes, bytearray, io.BytesIO, glasswall.content_management.policies.Policy], optional): The content management policy .xml to use.
            raise_unsupported (bool, optional): Default True. Raise exceptions when Glasswall encounters an error. Fail silently if False.

        Returns:
            protected_archives_dict (dict): A dictionary of file paths relative to input_directory, and glasswall.GwReturnObj containing `output_file` and output_report` attributes of type: bytes.
        """
        protected_archives_dict = {}
        # Call protect_archive on each file in input_directory to output_directory
        for input_file in utils.list_file_paths(input_directory):
            relative_path = os.path.relpath(input_file, input_directory)
            output_file = None if output_directory is None else os.path.join(os.path.abspath(output_directory), relative_path)
            output_report = None if output_report_directory is None else os.path.join(os.path.abspath(output_report_directory), relative_path + ".xml")

            gw_return_object = self.protect_archive(
                input_file=input_file,
                output_file=output_file,
                output_report=output_report,
                content_management_policy=content_management_policy,
                raise_unsupported=raise_unsupported,
            )

            protected_archives_dict[relative_path] = gw_return_object

        return protected_archives_dict
