# Binary Analysis Next Generation (BANG!)
#
# This file is part of BANG.
#
# BANG is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License, version 3,
# as published by the Free Software Foundation.
#
# BANG is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License, version 3, along with BANG.  If not, see
# <http://www.gnu.org/licenses/>
#
# Copyright Armijn Hemel
# Licensed under the terms of the GNU Affero General Public License
# version 3
# SPDX-License-Identifier: AGPL-3.0-only

import os
import pathlib

from bang.UnpackParser import UnpackParser, check_condition
from bang.UnpackParserException import UnpackParserException
from kaitaistruct import ValidationNotEqualError
from . import llvm_ir_wrapper

class LlvmIrWrapperUnpackParser(UnpackParser):
    extensions = []
    signatures = [
        (0, b'\xde\xc0\x17\x0b')
    ]
    pretty_name = 'llvm_ir_wrapper'

    def parse(self):
        try:
            self.data = llvm_ir_wrapper.LlvmIrWrapper.from_io(self.infile)
        except (Exception, ValidationNotEqualError) as e:
            raise UnpackParserException(e.args)
        self.unpacked_size = self.data.ofs_bytecode + self.data.len_bytecode
        check_condition(self.infile.size >= self.unpacked_size, "not enough data")

    # make sure that self.unpacked_size is not overwritten
    def calculate_unpacked_size(self):
        pass

    labels = ['llvm']
    metadata = {}

